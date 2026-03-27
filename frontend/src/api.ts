import type {
  ApiError,
  Auction,
  AuctionCreatePayload,
  Bid,
  CurrentUser,
  CurrentUserUpdatePayload,
  RegisterPayload,
  RegisterResponse,
  TokenPair,
} from "./types";

const API_BASE_KEY = "bidfall_api_base";
const TOKENS_KEY = "bidfall_tokens";

export function getStoredApiBase(): string {
  return localStorage.getItem(API_BASE_KEY) ?? "";
}

export function setStoredApiBase(value: string) {
  localStorage.setItem(API_BASE_KEY, value.replace(/\/+$/, ""));
}

export function getStoredTokens(): TokenPair | null {
  const raw = localStorage.getItem(TOKENS_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as TokenPair;
  } catch {
    return null;
  }
}

export function setStoredTokens(tokens: TokenPair | null) {
  if (!tokens) {
    localStorage.removeItem(TOKENS_KEY);
    return;
  }
  localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
}

async function parseJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(`Неверный ответ сервера (HTTP ${response.status})`);
    }
  }
  if (!response.ok) {
    const error = (data ?? {}) as ApiError;
    const detailText = formatApiErrorData(data);
    const err = new Error(
      String(detailText ?? error.error ?? error.detail ?? `HTTP ${response.status}`),
    ) as Error & { status?: number };
    err.status = response.status;
    throw err;
  }
  return data as T;
}

function formatApiErrorData(data: unknown): string | null {
  if (!data) return null;
  if (typeof data === "string") return data;
  if (Array.isArray(data)) {
    const parts = data.map((item) => formatApiErrorData(item)).filter(Boolean) as string[];
    return parts.length ? parts.join("; ") : null;
  }
  if (typeof data === "object") {
    const entries = Object.entries(data as Record<string, unknown>);
    if (!entries.length) return null;
    const parts = entries
      .map(([key, value]) => {
        const rendered = formatApiErrorData(value);
        return rendered ? `${key}: ${rendered}` : null;
      })
      .filter(Boolean) as string[];
    return parts.length ? parts.join("; ") : null;
  }
  return String(data);
}

async function request<T>(
  path: string,
  init?: RequestInit & { baseUrl?: string; token?: string | null },
) {
  const baseUrl = (init?.baseUrl ?? getStoredApiBase()).replace(/\/+$/, "");
  const { baseUrl: _baseUrl, token, ...requestInit } = init ?? {};
  const headers = new Headers(requestInit.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const makeRequest = async (url: string) => {
    const response = await fetch(url, {
      ...requestInit,
      headers,
    });
    return parseJson<T>(response);
  };

  try {
    return await makeRequest(`${baseUrl}${path}`);
  } catch (error) {
    if (!baseUrl || !shouldFallbackToSameOrigin(error)) throw error;
    // Fallback to same-origin (/api via Vite proxy) if a stale custom API base was saved.
    return makeRequest(path);
  }
}

function shouldFallbackToSameOrigin(error: unknown) {
  if (!(error instanceof Error)) return false;
  const status = (error as Error & { status?: number }).status;
  if (status === 404 || status === 405) return true;
  if (error.message.startsWith("Неверный ответ сервера")) return true;
  // fetch() network errors in browsers often surface as TypeError("Failed to fetch")
  return /Failed to fetch|NetworkError|Load failed/i.test(error.message);
}

export async function registerUser(payload: RegisterPayload, baseUrl?: string) {
  return request<RegisterResponse>("/api/auth/register/", {
    method: "POST",
    body: JSON.stringify(payload),
    baseUrl,
  });
}

export async function loginUser(
  username: string,
  password: string,
  baseUrl?: string,
) {
  return request<TokenPair>("/api/auth/login/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    baseUrl,
  });
}

export async function fetchActiveAuctions(baseUrl?: string) {
  return request<Auction[]>("/api/auctions/active/", { method: "GET", baseUrl });
}

export async function fetchAuctions(baseUrl?: string, token?: string) {
  return request<Auction[]>("/api/auctions/", { method: "GET", baseUrl, token });
}

export async function fetchAuction(id: number, baseUrl?: string, token?: string) {
  return request<Auction>(`/api/auctions/${id}/`, { method: "GET", baseUrl, token });
}

export async function fetchAuctionBids(
  id: number,
  token: string,
  baseUrl?: string,
) {
  return request<Bid[]>(`/api/auctions/${id}/bids/`, {
    method: "GET",
    token,
    baseUrl,
  });
}

export async function submitBid(
  id: number,
  token: string,
  payload: { bid_amount: string; comment?: string },
  baseUrl?: string,
) {
  return request<{ redirect_url: string }>(`/api/auctions/${id}/bids/`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
    baseUrl,
  });
}

export async function createAuction(
  payload: AuctionCreatePayload,
  token: string,
  baseUrl?: string,
) {
  return request<Auction>("/api/auctions/", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
    baseUrl,
  });
}

export async function updateAuction(
  id: number,
  payload: Partial<AuctionCreatePayload>,
  token: string,
  baseUrl?: string,
) {
  return request<Auction>(`/api/auctions/${id}/`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
    baseUrl,
  });
}

export async function closeAuction(
  id: number,
  token: string,
  baseUrl?: string,
) {
  return request<Auction>(`/api/auctions/${id}/close/`, {
    method: "POST",
    token,
    body: JSON.stringify({}),
    baseUrl,
  });
}

export async function publishAuction(
  id: number,
  token: string,
  baseUrl?: string,
) {
  return request<{ redirect_url: string }>(`/api/auctions/${id}/publish/`, {
    method: "POST",
    token,
    body: JSON.stringify({}),
    baseUrl,
  });
}

export async function fetchAuctionWinner(
  id: number,
  token: string,
  baseUrl?: string,
) {
  return request<Bid>(`/api/auctions/${id}/winner/`, {
    method: "GET",
    token,
    baseUrl,
  });
}

export async function fetchServerTime(baseUrl?: string) {
  return request<{ server_time: string; server_time_ms: number }>("/api/server-time/", {
    method: "GET",
    baseUrl,
  });
}

export async function fetchCurrentUser(token: string, baseUrl?: string) {
  return request<CurrentUser>("/api/auth/me/", {
    method: "GET",
    token,
    baseUrl,
  });
}

export async function fetchMyAuctions(token: string, baseUrl?: string) {
  return request<Auction[]>("/api/auth/me/auctions/", {
    method: "GET",
    token,
    baseUrl,
  });
}

export async function fetchMyParticipatingAuctions(token: string, baseUrl?: string) {
  return request<Auction[]>("/api/auth/me/participating-auctions/", {
    method: "GET",
    token,
    baseUrl,
  });
}

export async function updateCurrentUser(
  payload: CurrentUserUpdatePayload,
  token: string,
  baseUrl?: string,
) {
  return request<CurrentUser>("/api/auth/me/", {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
    baseUrl,
  });
}

export function normalizeAuction(auction: Auction): Auction {
  return {
    ...auction,
    lots: auction.lots ?? auction.catalog_items ?? [],
  };
}
