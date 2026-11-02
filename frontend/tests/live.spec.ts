import { expect, test } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

test('live local models complete all three games and fit desktop/mobile', async ({ page, request }) => {
  test.skip(!process.env.LIVE_API, 'Enable LIVE_API=1 to run real training and local Laya.');
  test.setTimeout(300_000);
  const directory = resolve('../verification/screenshots');
  await mkdir(directory, { recursive: true });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const health = await (await request.get('/api/health')).json();
  expect(health.status).toBe('ok');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await expect(page.getByRole('button', { name: '预测下一期号码', exact: true })).toBeVisible();
  await page.screenshot({ path: resolve(directory, 'desktop-idle.png'), fullPage: true });
  const results = [];
  for (const [game, name, frontCount, backCount] of [
    ['ssq', '双色球', 6, 1], ['dlt', '大乐透', 5, 2], ['qlc', '七乐彩', 7, 1],
  ] as const) {
    await page.setViewportSize({ width: 1440, height: 900 });
    if (game !== 'ssq') {
      await page.getByRole('button', { name: '选择彩种' }).click();
      await page.getByRole('menuitemradio', { name, exact: true }).click();
    }
    const submitted = page.waitForResponse(response => response.url().endsWith('/api/predictions') && response.request().method() === 'POST');
    await page.getByRole('button', { name: '预测下一期号码', exact: true }).click();
    const response = await submitted;
    expect(response.status()).toBe(202);
    const job = await response.json();
    await expect(page.getByTestId('progress')).toBeVisible();
    if (game === 'ssq') {
      await expect(page.getByTestId('spinner')).toBeVisible();
      const before = await page.getByTestId('spinner').evaluate(el => getComputedStyle(el).transform);
      await page.waitForTimeout(130);
      const after = await page.getByTestId('spinner').evaluate(el => getComputedStyle(el).transform);
      expect(before).not.toBe(after);
      await page.screenshot({ path: resolve(directory, 'desktop-working.png'), fullPage: true });
    }
    await expect(page.getByRole('button', { name: '预测下一期号码', exact: true })).toBeEnabled({ timeout: 180_000 });
    const finished = await (await request.get('/api/jobs/' + job.id)).json();
    expect(finished.status, finished.error || 'job must complete using real models').toBe('complete');
    const result = finished.result;
    expect(result.front).toHaveLength(frontCount); expect(result.back).toHaveLength(backCount);
    expect(new Set(result.front).size).toBe(frontCount);
    expect(result.attempts).toBeLessThanOrEqual(3);
    expect(result.selection_provenance.every((round: any) => !round.decision.usage.truncated)).toBe(true);
    expect(result.engine).toContain('laya');
    const stages = finished.events.map((event: any) => event.stage);
    expect(stages).toContain('prediction'); expect(stages).toContain('laya');
    await expect(page.locator('.number')).toHaveCount(frontCount + backCount);
    if (game === 'ssq') await expect(page.getByTestId('back-number')).toHaveCSS('color', 'rgb(76, 154, 255)');
    await page.mouse.move(0, 0); await page.waitForTimeout(250);
    await page.screenshot({ path: resolve(directory, `desktop-${game}.png`), fullPage: true });
    for (const width of [390, 320, 601, 740, 800]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const boxes = await page.locator('.number').evaluateAll(elements => elements.map(el => {
        const box = el.getBoundingClientRect(); return { left: box.left, right: box.right, width: box.width };
      }));
      expect(boxes.every((box, index) => box.left >= 0 && box.right <= width && (!index || box.left >= boxes[index - 1].right))).toBe(true);
      await page.screenshot({ path: resolve(directory, `mobile-${width}-${game}.png`), fullPage: true });
    }
    results.push(finished);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '选择彩种' }).click();
  await expect(page.getByRole('menu')).toBeVisible();
  await page.waitForTimeout(220);
  await page.screenshot({ path: resolve(directory, 'mobile-menu.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);
  expect(errors).toEqual([]);
  await writeFile(resolve('../verification/browser-live.json'), JSON.stringify({ health, errors, jobs: results }, null, 2));
});
