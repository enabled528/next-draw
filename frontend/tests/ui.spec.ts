import { expect, test } from '@playwright/test';

const games = [
  { id: 'ssq', name: '双色球', enabled: true, data_date: '2026-11-01', records: 3522 },
  { id: 'dlt', name: '大乐透', enabled: true, data_date: '2026-10-31', records: 2942 },
  { id: 'qlc', name: '七乐彩', enabled: true, data_date: '2026-10-30', records: 3005 },
  { id: 'qxc', name: '七星彩', enabled: false, reason: '数据来源与模型尚未验证' },
];

test.beforeEach(async ({ page }) => {
  await page.route('**/api/games', route => route.fulfill({ json: games }));
});

test('game menu opens by keyboard and progress is absent before clicking', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: '预测下一期号码', exact: true })).toBeVisible();
  await expect(page.getByTestId('progress')).toHaveCount(0);
  const trigger = page.getByRole('button', { name: '选择彩种' });
  await trigger.focus(); await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('menu')).toBeVisible();
  await page.getByRole('menuitemradio', { name: '大乐透', exact: true }).click();
  await expect(page.getByTestId('selected-game')).toHaveText('大乐透');
  await expect(page.getByRole('menu')).toHaveCount(0);
});

test('real API-shaped stages fade and SSQ back number is blue', async ({ page }) => {
  let polls = 0;
  const id = '00000000-0000-4000-8000-000000000001';
  await page.route('**/api/predictions', route => route.fulfill({ status: 202, json: { id, game: 'ssq', status: 'queued', message: '正在准备本次预测', events: [] } }));
  await page.route('**/api/jobs/' + id, async route => {
    polls++;
    await route.fulfill({ json: polls < 4 ? { id, game: 'ssq', status: 'running', message: polls < 3 ? '正在获取新增开奖数据' : '正在加载号码模型' } : {
      id, game: 'ssq', status: 'complete', message: '本次号码已生成', result: { game: 'ssq', game_name: '双色球', front: [1, 2, 3, 4, 5, 6], back: [7], score: 80, threshold_met: true, attempts: 1, candidates_compared: 4,
      data_date: '2026-11-01', history_count: 3522, elapsed_seconds: 1, model_source: 'memory', latest_issue: '26125' },
    } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '预测下一期号码', exact: true }).click();
  await expect(page.getByTestId('progress')).toBeVisible();
  await expect(page.getByText('正在获取新增开奖数据', { exact: true })).toBeVisible();
  expect(await page.getByTestId('progress-text').evaluate(el => getComputedStyle(el).transitionProperty)).toContain('opacity');
  await expect(page.getByTestId('back-number')).toHaveText('07');
  await expect(page.getByTestId('back-number')).toHaveCSS('color', 'rgb(76, 154, 255)');
  await expect(page.getByTestId('spinner')).toHaveCount(0);
});

test('mobile menu fits and reduced motion stops spinning', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByRole('button', { name: '选择彩种' }).click();
  await expect(page.getByRole('menuitemradio', { name: '七星彩', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test('failure ends the spinner and allows a new prediction', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000002';
  await page.route('**/api/predictions', route => route.fulfill({ status: 202, json: { id, game: 'ssq', status: 'queued', message: '排队中' } }));
  await page.route('**/api/jobs/' + id, route => route.fulfill({ json: { id, game: 'ssq', status: 'failed', message: '运行未完成', error: 'Laya 模型无法加载' } }));
  await page.goto('/');
  await page.getByRole('button', { name: '预测下一期号码', exact: true }).click();
  await expect(page.getByText('Laya 模型无法加载', { exact: true })).toBeVisible();
  await expect(page.getByTestId('spinner')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '预测下一期号码', exact: true })).toBeEnabled();
});

test('cancellation and reduced motion are explicit', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000003';
  let cancelled = false;
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/predictions', route => route.fulfill({ status: 202, json: { id, game: 'ssq', status: 'queued', message: '排队中' } }));
  await page.route('**/api/jobs/' + id, route => route.fulfill({ json: { id, game: 'ssq', status: cancelled ? 'cancelled' : 'running', message: cancelled ? '本次运行已取消' : '正在加载模型' } }));
  await page.route('**/api/jobs/' + id + '/cancel', route => { cancelled = true; return route.fulfill({ json: { id, game: 'ssq', status: 'cancelled', message: '本次运行已取消' } }); });
  await page.goto('/'); await page.getByRole('button', { name: '预测下一期号码', exact: true }).click();
  await expect(page.getByTestId('spinner')).toHaveCSS('animation-name', 'none');
  await page.getByRole('button', { name: '取消本次运行' }).click();
  await expect(page.getByText('本次运行已取消', { exact: true })).toBeVisible();
  await expect(page.getByTestId('spinner')).toHaveCount(0);
});

test('reload reconnects to the same running job without a second submission', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000004'; let posts = 0;
  await page.route('**/api/predictions', route => { posts++; return route.fulfill({ status: 202, json: { id, game: 'ssq', status: 'queued', message: '排队中' } }); });
  await page.route('**/api/jobs/' + id, route => route.fulfill({ json: { id, game: 'ssq', status: 'running', message: '正在加载模型' } }));
  await page.goto('/'); await page.getByRole('button', { name: '预测下一期号码', exact: true }).click();
  await expect(page.getByText('正在加载模型', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('正在加载模型', { exact: true })).toBeVisible();
  expect(posts).toBe(1);
});

test('a permanently missing job releases stale session state', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000005';
  await page.addInitScript(value => sessionStorage.setItem('next-draw-active-job', JSON.stringify({ id: value, game: 'ssq' })), id);
  await page.route('**/api/jobs/' + id, route => route.fulfill({ status: 404, json: { detail: '任务不存在' } }));
  await page.goto('/');
  await expect(page.getByRole('button', { name: '预测下一期号码', exact: true })).toBeEnabled();
  expect(await page.evaluate(() => sessionStorage.getItem('next-draw-active-job'))).toBeNull();
});

test('an ambiguous submission keeps its identity across reload', async ({ page }) => {
  const ids: string[] = [];
  await page.route('**/api/predictions', async route => {
    ids.push(route.request().postDataJSON().request_id);
    if (ids.length === 1) return route.abort('failed');
    return route.fulfill({ status: 202, json: { id: '00000000-0000-4000-8000-000000000006', game: 'ssq', status: 'cancelled', message: '本次运行已取消' } });
  });
  await page.goto('/'); await page.getByRole('button', { name: '预测下一期号码', exact: true }).click();
  await expect(page.locator('.has-error')).toBeVisible();
  await page.reload();
  await expect.poll(() => ids.length).toBe(2);
  expect(ids[0]).toBe(ids[1]);
});

test('QLC results fit intermediate widths and a pointer menu closes with Escape', async ({ page }) => {
  await page.route('**/api/predictions', route => route.fulfill({ status: 202, json: { id: '00000000-0000-4000-8000-000000000007', game: 'qlc', status: 'complete', message: '已生成', result: {
    game: 'qlc', game_name: '七乐彩', front: [1,2,3,4,5,6,7], back: [8], score: 80, threshold_met: true, candidates_compared: 4, attempts: 1,
    data_date: '2026-10-30', history_count: 3005, elapsed_seconds: 1, model_source: 'memory', latest_issue: '26125',
  } } }));
  await page.goto('/'); await page.getByRole('button', { name: '选择彩种' }).click();
  await page.getByRole('menuitemradio', { name: '七乐彩', exact: true }).click();
  await page.getByRole('button', { name: '预测下一期号码', exact: true }).click();
  await expect(page.locator('.number')).toHaveCount(8);
  for (const width of [601, 680, 740, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.getByRole('button', { name: '选择彩种' }).click(); await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);
});
