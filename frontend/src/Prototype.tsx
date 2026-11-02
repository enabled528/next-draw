import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Info, LockKeyhole, X } from 'lucide-react';
import { ApiError, request, type GameId, type GameInfo, type Job, type PredictionResult } from './api';
import './prototype.css';

const defaults: GameInfo[] = [
  { id: 'ssq', name: '双色球', enabled: true },
  { id: 'dlt', name: '大乐透', enabled: true },
  { id: 'qlc', name: '七乐彩', enabled: true },
  { id: 'qxc', name: '七星彩', enabled: false, reason: '数据来源与模型尚未验证' },
];
const storageKey = 'next-draw-active-job';
const pendingKey = 'next-draw-pending-request';
type Submission = { game: GameId; request_id: string };
function readPending(): Submission | null {
  try { return JSON.parse(sessionStorage.getItem(pendingKey) || 'null'); }
  catch { return null; }
}
function readActive(): { id: string; game: GameId } | null {
  try { return JSON.parse(sessionStorage.getItem(storageKey) || 'null'); }
  catch { return null; }
}

function FadeText({ text }: { text: string }) {
  const [shown, setShown] = useState(text);
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    if (text === shown) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(text); setVisible(true); return;
    }
    setVisible(false);
    const timer = setTimeout(() => { setShown(text); setVisible(true); }, 120);
    return () => clearTimeout(timer);
  }, [text, shown]);
  return <span data-testid="progress-text" className="progress-text" style={{ opacity: visible ? 1 : 0 }}>{shown}</span>;
}

export function Prototype() {
  const initial = useRef(readActive());
  const initialPending = useRef(readPending());
  const [games, setGames] = useState(defaults);
  const [selected, setSelected] = useState<GameId>(initial.current?.game || initialPending.current?.game || 'ssq');
  const [menuOpen, setMenuOpen] = useState(false);
  const [keyboardMenu, setKeyboardMenu] = useState(false);
  const [busy, setBusy] = useState(Boolean(initial.current || initialPending.current));
  const [started, setStarted] = useState(Boolean(initial.current || initialPending.current));
  const [message, setMessage] = useState('正在连接任务');
  const [result, setResult] = useState<PredictionResult | null>(null);
  const [error, setError] = useState('');
  const [jobId, setJobId] = useState<string | null>(initial.current?.id || null);
  const [connectionLost, setConnectionLost] = useState(false);
  const [retry, setRetry] = useState(0);
  const [details, setDetails] = useState(false);
  const [cancelPending, setCancelPending] = useState(false);
  const pendingRequest = useRef<Submission | null>(initialPending.current);
  const resumed = useRef(false);
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let alive = true;
    request<GameInfo[]>('/api/games').then(data => { if (alive) setGames(data); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const accept = useCallback((job: Job) => {
    setMessage(job.message);
    if (['complete', 'failed', 'cancelled'].includes(job.status)) {
      setBusy(false); setCancelPending(false); setJobId(null);
      sessionStorage.removeItem(storageKey); pendingRequest.current = null;
      sessionStorage.removeItem(pendingKey);
      if (job.status === 'complete' && job.result) { setResult(job.result); setError(''); }
      else if (job.status === 'failed') setError(job.error || '本次运行未完成，请重试');
      return true;
    }
    setBusy(true);
    return false;
  }, []);

  const submit = useCallback(async (payload: Submission) => {
    try {
      sessionStorage.setItem(pendingKey, JSON.stringify(payload));
      const job = await request<Job>('/api/predictions', payload);
      if (!accept(job)) {
        sessionStorage.setItem(storageKey, JSON.stringify({ id: job.id, game: job.game }));
        sessionStorage.removeItem(pendingKey); setJobId(job.id);
      }
    } catch (cause) {
      setBusy(false); setError(cause instanceof Error ? cause.message : '无法创建任务，请重试');
    }
  }, [accept]);

  useEffect(() => {
    if (!resumed.current && !initial.current && initialPending.current) {
      resumed.current = true; setMessage('正在恢复已提交的请求'); void submit(initialPending.current);
    }
  }, [submit]);

  useEffect(() => {
    if (!jobId) return;
    let alive = true; let timer: ReturnType<typeof setTimeout>; let failures = 0;
    const poll = async () => {
      try {
        const job = await request<Job>(`/api/jobs/${jobId}`);
        if (!alive) return;
        failures = 0;
        if (accept(job)) return;
      } catch (cause) {
        if (!alive) return;
        if (cause instanceof ApiError && cause.status === 404) {
          sessionStorage.removeItem(storageKey); sessionStorage.removeItem(pendingKey); pendingRequest.current = null;
          setJobId(null); setBusy(false); setConnectionLost(false); setCancelPending(false);
          setError('原任务已不存在，可以重新预测'); return;
        }
        if (++failures >= 3) {
          setBusy(false); setConnectionLost(true);
          setError(`连接暂时中断，任务仍可能在运行。${cause instanceof Error ? cause.message : ''}`);
          return;
        }
      }
      timer = setTimeout(poll, 450);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [jobId, retry, accept]);

  useEffect(() => {
    if (!menuOpen) return;
    const outside = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setMenuOpen(false); trigger.current?.focus(); } };
    document.addEventListener('keydown', escape);
    if (keyboardMenu) menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [menuOpen, keyboardMenu]);

  const start = async () => {
    if (busy) return;
    setStarted(true); setError(''); setDetails(false); setMenuOpen(false);
    if (connectionLost && jobId) {
      setBusy(true); setConnectionLost(false); setMessage('正在重新连接任务'); setRetry(value => value + 1); return;
    }
    setBusy(true); setResult(null); setMessage('正在准备本次预测');
    const payload = pendingRequest.current?.game === selected ? pendingRequest.current : { game: selected, request_id: crypto.randomUUID() };
    pendingRequest.current = payload;
    await submit(payload);
  };
  const cancel = async () => {
    if (!jobId || cancelPending) return;
    setCancelPending(true);
    try { accept(await request<Job>(`/api/jobs/${jobId}/cancel`, {})); }
    catch { setCancelPending(false); setError('取消请求未送达，请稍后再试'); }
  };
  const currentGame = games.find(game => game.id === selected) || defaults[0];
  const selectGame = (game: GameInfo) => {
    if (!game.enabled) return;
    setSelected(game.id as GameId); setMenuOpen(false); setResult(null); setStarted(false); setError(''); setDetails(false);
    pendingRequest.current = null; trigger.current?.focus();
    sessionStorage.removeItem(pendingKey);
  };
  const menuKeys = (event: React.KeyboardEvent) => {
    const items = [...(menu.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])];
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'Escape') { setMenuOpen(false); trigger.current?.focus(); }
    else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items[next]?.focus();
    } else if (event.key === 'Tab') setMenuOpen(false);
  };

  return <main className="next-draw">
    <header className="page-header"><h1>NEXT DRAW<span className="brand-dot">.</span></h1><span>下一期</span></header>
    <section className="workspace" aria-label="号码预测">
      <div className="experience">
        <div className="result-zone" aria-live="polite">
          {result && <div className="result-content">
            <div className="result-caption">{result.game_name} <span>下一期号码</span></div>
            <div className="numbers" aria-label="本次生成号码">
              {result.front.map(number => <span className="number" key={number}>{String(number).padStart(2, '0')}</span>)}
              <span className="number-divider" aria-hidden="true">/</span>
              {result.back.map(number => <span key={number} data-testid="back-number" className={`number ${result.game === 'ssq' ? 'blue-number' : ''}`}>{String(number).padStart(2, '0')}</span>)}
            </div>
            <div className="result-meta"><span>Laya {result.score.toFixed(2)} / 100</span><span>比较 {result.candidates_compared} 组候选</span>
              <button className="icon-button detail-button" title="查看本次运行记录" aria-label="查看本次运行记录" aria-expanded={details} onClick={() => setDetails(!details)}><Info size={15} /></button>
            </div>
            {!result.threshold_met && <p className="threshold-note">本轮未达 75 分，保留最高评分候选</p>}
          </div>}
        </div>
        <div className="action-area">
          <div className="selected-label" data-testid="selected-game">{currentGame.name}</div>
          <div className="split-button" aria-busy={busy}>
            <button className="predict-button" onClick={() => void start()} disabled={busy}>{connectionLost ? '重新连接任务' : '预测下一期号码'}</button>
            <button ref={trigger} className="menu-trigger" aria-label="选择彩种" aria-haspopup="menu" aria-expanded={menuOpen} aria-controls="game-menu" disabled={busy || connectionLost}
              onClick={() => { setKeyboardMenu(false); setMenuOpen(!menuOpen); }}
              onKeyDown={event => { if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); setKeyboardMenu(true); setMenuOpen(true); } }}>
              <ChevronDown size={20} className={menuOpen ? 'chevron is-open' : 'chevron'} />
            </button>
          </div>
          {menuOpen && <div ref={menu} id="game-menu" role="menu" aria-label="彩种" className={`game-menu ${keyboardMenu ? 'keyboard-menu' : ''}`} onKeyDown={menuKeys}>
            {games.map(game => <button key={game.id} role="menuitemradio" aria-checked={selected === game.id} disabled={!game.enabled} title={game.reason} onClick={() => selectGame(game)}>
              <span>{game.name}</span>{!game.enabled ? <LockKeyhole size={14} aria-hidden="true" /> : selected === game.id ? <Check size={16} aria-hidden="true" /> : null}
            </button>)}
          </div>}
          <div className="progress-slot">
            {started && <div className={`progress ${error ? 'has-error' : ''}`} data-testid="progress" role="status">
              {busy && <span className="spinner" data-testid="spinner" aria-hidden="true" />}
              <FadeText text={error || message} />
              {busy && jobId && <button className="icon-button cancel-button" title="取消本次运行" aria-label="取消本次运行" disabled={cancelPending} onClick={() => void cancel()}><X size={15} /></button>}
            </div>}
          </div>
        </div>
        {result?.warnings?.map(warning => <p className="cache-warning" key={warning}>{warning}</p>)}
        {details && result && <dl className="run-details">
          <div><dt>历史记录</dt><dd>{result.history_count.toLocaleString()} 期 · 截至 {result.data_date}</dd></div>
          <div><dt>最近期号</dt><dd>{result.latest_issue}</dd></div>
          <div><dt>本次耗时</dt><dd>{result.elapsed_seconds.toFixed(2)} 秒 · {result.attempts} 轮</dd></div>
          <div><dt>号码模型</dt><dd>LSTM + CRF · {result.model_source === 'trained' ? '新训练' : '已缓存'}</dd></div>
          <div><dt>决策模型</dt><dd>Laya · 本地运行</dd></div>
        </dl>}
      </div>
    </section>
    <footer className="page-footer"><span>{result ? `数据截至 ${result.data_date}` : currentGame.data_date ? `数据截至 ${currentGame.data_date}` : 'LSTM + CRF / LAYA'}</span><span>仅供模型实验</span></footer>
  </main>;
}
