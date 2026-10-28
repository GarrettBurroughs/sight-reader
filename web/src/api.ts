// Typed calls to the API server (server/app.py), reached through the Vite proxy at /api.

export type Mode = "wait" | "tempo";
export type Hands = "both" | "right" | "left";
export type Length = "excerpt" | "section" | "full"; // 8 bars, 16 bars, the whole piece
/** Keyed "wait", "tempo", "wait:left", "tempo:right"... (see levelKey). */
export type Levels = Record<string, number>;

export const levelKey = (mode: Mode, hands: Hands) => (hands === "both" ? mode : `${mode}:${hands}`);

export type Player = {
  id: number;
  name: string;
  created_at: string;
  levels: Levels;
  attempts: number;
  last_played: string | null;
};

export type Excerpt = {
  id: string;
  piece_id: string;
  kind: Length;
  title: string;
  composer: string | null;
  grade: number;
  difficulty: number;
  start_bar: string;
  n_bars: number;
  time_signature: string;
  key_fifths: number;
  notes_per_quarter: number;
  no_license_conflict: boolean;
  source: "pdmx" | "generated";
  score_url: string;
};

export type ExcerptDetail = Excerpt & {
  genres: string | null;
  license: string | null;
  rating: number | null;
  n_favorites: number;
  features: Record<string, unknown>;
  terms: Record<string, number>;
  attempts: { id: number; mode: Mode; hands: Hands; finished_at: string; performance: number; level_before: number; level_after: number; player: string }[];
};

export type Attempt = {
  id: number;
  excerpt_id: string;
  piece_id: string;
  title: string | null;
  grade: number;
  mode: Mode;
  hands: Hands;
  finished_at: string;
  bpm: number | null;
  duration_ms: number;
  wrong: number;
  wrong_right: number | null;
  wrong_left: number | null;
  missed_right: number | null;
  missed_left: number | null;
  note_pct: number | null;
  timing_pct: number | null;
  performance: number;
  level_before: number;
  level_after: number;
};

/** Wrong presses put down to each hand (by the nearest expected note), and tempo-mode misses. */
type ByHand = { hands: Hands; wrong_right: number; wrong_left: number; missed_right?: number; missed_left?: number };

/** What a finished session reports; the server works out performance and the new level. */
export type AttemptResult = ByHand &
  (
  | { mode: "wait"; steps: number; wrong: number; duration_ms: number }
  | {
      mode: "tempo";
      bpm: number;
      duration_ms: number;
      total: number;
      played: number;
      missed: number;
      wrong: number;
      note_pct: number;
      timing_pct: number;
      mean_offset_ms: number;
    }
  );

export type LevelChange = { performance: number; level_before: number; level_after: number };

export type Summary = {
  pieces: number;
  excerpts: number;
  players: number;
  attempts: number;
  generated: number;
  license_only: boolean;
  grades: { grade: number; excerpts: number; sections: number; full: number; license_ok: number; pieces: number }[];
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail, () => res.statusText);
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

function query(params: Record<string, string | number | boolean | null | undefined>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  return q.toString();
}

export const api = {
  players: () => call<Player[]>("GET", "/api/players"),
  createPlayer: (name: string, level?: number) => call<Player>("POST", "/api/players", { name, level }),
  updatePlayer: (id: number, patch: { name?: string; levels?: Partial<Levels> }) =>
    call<{ id: number; levels: Levels }>("PATCH", `/api/players/${id}`, patch),
  deletePlayer: (id: number) => call<void>("DELETE", `/api/players/${id}`),
  attempts: (playerId: number, limit = 200) => call<Attempt[]>("GET", `/api/players/${playerId}/attempts?limit=${limit}`),
  next: (playerId: number, mode: Mode, hands: Hands, length: Length, grade?: number) =>
    call<{ level: number; excerpt: Excerpt }>("GET", `/api/next?${query({ player_id: playerId, mode, hands, length, grade })}`),
  recordAttempt: (playerId: number, excerptId: string, result: AttemptResult) =>
    call<LevelChange>("POST", "/api/attempts", { player_id: playerId, excerpt_id: excerptId, ...result }),
  excerpt: (id: string) => call<ExcerptDetail>("GET", `/api/excerpts/${encodeURIComponent(id)}`),
  library: (params: { grade?: number; q?: string; source?: string; kind?: string; license_only?: boolean; sort?: string; order?: string; limit?: number; offset?: number }) =>
    call<{ total: number; rows: (Excerpt & { attempts: number })[] }>("GET", `/api/library?${query(params)}`),
  summary: () => call<Summary>("GET", "/api/admin/summary"),
};
