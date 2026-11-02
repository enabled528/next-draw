export type GameId = 'ssq' | 'dlt' | 'qlc';
export interface GameInfo {
  id: string; name: string; enabled: boolean; reason?: string;
  data_date?: string; records?: number; latest_issue?: string;
}
export interface PredictionResult {
  game: GameId; game_name: string; front: number[]; back: number[];
  score: number; threshold_met: boolean; attempts: number; candidates_compared: number;
  data_date: string; latest_issue: string; history_count: number;
  elapsed_seconds: number; model_source: string; warnings?: string[];
}
export interface Job {
  id: string; game: GameId;
  status: 'queued' | 'running' | 'cancelling' | 'complete' | 'failed' | 'cancelled';
  message: string; result?: PredictionResult | null; error?: string;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}
