import type {
  ApiError,
  Auction,
  AuctionCreatePayload,
  AuctionLotInput,
  Bid,
  CatalogItem,
  CatalogItemsQuery,
  CatalogItemsResponse,
  CatalogNode,
  CatalogNodesQuery,
  CatalogNodesResponse,
  CurrentUser,
  CurrentUserUpdatePayload,
  RegisterPayload,
  RegisterResponse,
  TokenPair,
} from "./types";

const API_BASE_KEY = "bidfall_api_base";
const TOKENS_KEY = "bidfall_tokens";
const CATALOG_API_MODE_KEY = "bidfall_catalog_api_mode";

export type CatalogApiMode = "mock" | "real";

type MaybePaginated<T> = T[] | { results?: T[] | null } | null | undefined;

const MOCK_CATALOG_NODES: CatalogNode[] = [
  { id: 1, name: "Строительство", parent_id: null, has_children: true, items_count: 0 },
  { id: 2, name: "Материалы", parent_id: 1, has_children: true, items_count: 0 },
  { id: 3, name: "Сухие смеси", parent_id: 2, has_children: false, items_count: 2 },
  { id: 4, name: "Инструмент", parent_id: 1, has_children: false, items_count: 1 },
];

const MOCK_CATALOG_ITEMS: CatalogItem[] = [
  {
    id: 101,
    code: "03.02.01",
    name: "Смесь штукатурная цементная",
    unit: "кг",
    node_id: 3,
    source_id: 1,
    default_quantity: "1.00",
  },
  {
    id: 102,
    code: "03.02.02",
    name: "Смесь кладочная универсальная",
    unit: "кг",
    node_id: 3,
    source_id: 1,
    default_quantity: "1.00",
  },
  {
    id: 103,
    code: "04.01.05",
    name: "Шпатель нержавеющий 350 мм",
    unit: "шт",
    node_id: 4,
    source_id: 1,
    default_quantity: "1.00",
  },
];

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

export function getCatalogApiMode(): CatalogApiMode {
  const raw = localStorage.getItem(CATALOG_API_MODE_KEY);
  if (raw === "mock" || raw === "real") return raw;
  const envMode = import.meta.env.VITE_CATALOG_API_MODE;
  return envMode === "mock" || envMode === "real" ? envMode : "real";
}

export function setCatalogApiMode(mode: CatalogApiMode | null) {
  if (!mode) {
    localStorage.removeItem(CATALOG_API_MODE_KEY);
    return;
  }
  localStorage.setItem(CATALOG_API_MODE_KEY, mode);
}

function toQueryString(params: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === "") return;
    qs.set(key, String(value));
  });
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
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

function normalizeListPayload<T>(payload: MaybePaginated<T>): T[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const results = (payload as { results?: unknown }).results;
    if (Array.isArray(results)) return results as T[];
  }
  return [];
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
  const data = await request<MaybePaginated<Auction>>("/api/auctions/active/", { method: "GET", baseUrl });
  return normalizeListPayload(data);
}

export async function fetchAuctions(baseUrl?: string, token?: string) {
  const data = await request<MaybePaginated<Auction>>("/api/auctions/", { method: "GET", baseUrl, token });
  return normalizeListPayload(data);
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

function queryMockCatalogNodes(query: CatalogNodesQuery): CatalogNodesResponse {
  let data = [...MOCK_CATALOG_NODES];
  if (query.parent_id !== undefined) {
    data = data.filter((item) => item.parent_id === query.parent_id);
  }
  if (query.q?.trim()) {
    const q = query.q.trim().toLowerCase();
    data = data.filter((item) => item.name.toLowerCase().includes(q));
  }
  const offset = Math.max(0, query.offset ?? 0);
  const limit = Math.max(1, (query.limit ?? data.length) || 1);
  const sliced = data.slice(offset, offset + limit);
  return { count: data.length, results: sliced };
}

function queryMockCatalogItems(query: CatalogItemsQuery): CatalogItemsResponse {
  let data = [...MOCK_CATALOG_ITEMS];
  if (query.node_id !== undefined) {
    data = data.filter((item) => item.node_id === query.node_id);
  }
  if (query.source_id !== undefined) {
    data = data.filter((item) => item.source_id === query.source_id);
  }
  if (query.q?.trim()) {
    const q = query.q.trim().toLowerCase();
    data = data.filter(
      (item) => item.name.toLowerCase().includes(q) || item.code.toLowerCase().includes(q),
    );
  }
  const offset = Math.max(0, query.offset ?? 0);
  const limit = Math.max(1, (query.limit ?? data.length) || 1);
  const sliced = data.slice(offset, offset + limit);
  return { count: data.length, results: sliced };
}

export async function fetchCatalogNodes(
  query: CatalogNodesQuery = {},
  baseUrl?: string,
  token?: string,
) {
  if (getCatalogApiMode() === "mock") {
    return queryMockCatalogNodes(query);
  }
  const suffix = toQueryString({
    parent_id: query.parent_id,
    q: query.q,
    limit: query.limit,
    offset: query.offset,
  });
  return request<CatalogNodesResponse>(`/api/catalog/nodes/${suffix}`, {
    method: "GET",
    baseUrl,
    token,
  });
}

export async function fetchCatalogItems(
  query: CatalogItemsQuery = {},
  baseUrl?: string,
  token?: string,
) {
  if (getCatalogApiMode() === "mock") {
    return queryMockCatalogItems(query);
  }
  const suffix = toQueryString({
    q: query.q,
    node_id: query.node_id,
    source_id: query.source_id,
    limit: query.limit,
    offset: query.offset,
  });
  return request<CatalogItemsResponse>(`/api/catalog/items/${suffix}`, {
    method: "GET",
    baseUrl,
    token,
  });
}

export async function fetchCatalogItemsByIds(
  ids: number[],
  baseUrl?: string,
  token?: string,
) {
  const normalizedIds = Array.from(new Set(ids.filter((id) => Number.isFinite(id))));
  if (!normalizedIds.length) return [];
  if (getCatalogApiMode() === "mock") {
    return MOCK_CATALOG_ITEMS.filter((item) => normalizedIds.includes(item.id));
  }
  const suffix = toQueryString({ ids: normalizedIds.join(",") });
  return request<CatalogItem[]>(`/api/catalog/items/by-ids/${suffix}`, {
    method: "GET",
    baseUrl,
    token,
  });
}

type LotValidationOptions = {
  requireAtLeastOne?: boolean;
};

export type LotValidationResult = {
  normalizedLots: AuctionLotInput[];
  errors: string[];
};

function normalizeQuantity(raw: string) {
  const normalized = raw.replace(",", ".").trim();
  return normalized;
}

export function validateAuctionLots(
  lots: AuctionLotInput[] | null | undefined,
  options: LotValidationOptions = { requireAtLeastOne: true },
): LotValidationResult {
  const errors: string[] = [];
  const input = Array.isArray(lots) ? lots : [];
  const deduped = new Map<number, string>();

  input.forEach((entry, index) => {
    const id = Number(entry?.id);
    const qty = normalizeQuantity(String(entry?.quantity ?? ""));
    if (!Number.isInteger(id) || id <= 0) {
      errors.push(`lots[${index}].id: должно быть положительным целым числом`);
      return;
    }
    const qtyNum = Number(qty);
    if (!Number.isFinite(qtyNum) || qtyNum <= 0) {
      errors.push(`lots[${index}].quantity: должно быть числом больше 0`);
      return;
    }
    deduped.set(id, qty);
  });

  if ((options.requireAtLeastOne ?? true) && deduped.size === 0) {
    errors.push("lots: выберите хотя бы один лот");
  }

  const normalizedLots = Array.from(deduped.entries()).map(([id, quantity]) => ({
    id,
    quantity,
  }));
  return { normalizedLots, errors };
}
