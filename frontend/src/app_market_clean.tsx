import { FormEvent, ReactNode, startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  closeAuction,
  createAuction,
  fetchCatalogItems,
  fetchCatalogItemsByIds,
  fetchCatalogNodes,
  fetchCurrentUser,
  fetchActiveAuctions,
  fetchAuction,
  fetchAuctionBids,
  fetchAuctionWinner,
  fetchMyAuctions,
  fetchAuctions,
  fetchMyParticipatingAuctions,
  fetchPartyByInn,
  fetchServerTime,
  getStoredApiBase,
  getStoredTokens,
  loginUser,
  normalizeAuction,
  publishAuction,
  registerUser,
  setStoredTokens,
  submitBid,
  toRussianErrorMessage,
  updateAuction,
  updateCurrentUser,
  validateAuctionLots,
} from "./api";
import type {
  Auction,
  AuctionCreatePayload,
  AuctionLot,
  AuctionLotInput,
  Bid,
  CatalogItem,
  CatalogNode,
  CurrentUser,
  CurrentUserUpdatePayload,
  JwtClaims,
  RegisterPayload,
  TokenPair,
  UserRole,
} from "./types";

type Route = { name: "home" } | { name: "browse" } | { name: "auction"; id: number } | { name: "sell" } | { name: "login" } | { name: "register" } | { name: "account" };
type Toast = { kind: "ok" | "error"; text: string } | null;
type CreateForm = {
  title: string;
  description: string;
  start_price: string;
  min_bid_decrement: string;
  start_date_local: string;
  end_date_local: string;
};
type AccountForm = {
  username: string;
  email: string;
  role: UserRole;
  company_name: string;
  inn: string;
  password: string;
};
type DraftEditForm = {
  title: string;
  description: string;
  start_price: string;
  min_bid_decrement: string;
  start_date_local: string;
  end_date_local: string;
};

const INN_REGEX = /^(?:\d{10}|\d{12})$/;

function dt(minutesAhead: number) {
  const d = new Date(Date.now() + minutesAhead * 60_000);
  const y = d.getFullYear(); const m = String(d.getMonth() + 1).padStart(2, "0"); const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0"); const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day}T${hh}:${mm}`;
}
const DEFAULT_CREATE: CreateForm = {
  title: "",
  description: "",
  start_price: "10000",
  min_bid_decrement: "500",
  start_date_local: dt(15),
  end_date_local: dt(24 * 60),
};
const DEFAULT_ACCOUNT_FORM: AccountForm = {
  username: "",
  email: "",
  role: "supplier",
  company_name: "",
  inn: "",
  password: "",
};
const DEFAULT_DRAFT_EDIT_FORM: DraftEditForm = {
  title: "",
  description: "",
  start_price: "",
  min_bid_decrement: "",
  start_date_local: "",
  end_date_local: "",
};

function parseRoute(path: string): Route {
  if (path === "/" || !path) return { name: "home" };
  if (path === "/auctions") return { name: "browse" };
  if (path === "/sell" || path === "/create-auction") return { name: "sell" };
  if (path === "/login") return { name: "login" };
  if (path === "/register") return { name: "register" };
  if (path === "/account") return { name: "account" };
  const m = path.match(/^\/auction\/(\d+)$/);
  return m ? { name: "auction", id: Number(m[1]) } : { name: "home" };
}
function routePath(r: Route) { return r.name === "auction" ? `/auction/${r.id}` : r.name === "home" ? "/" : `/${r.name === "browse" ? "auctions" : r.name === "sell" ? "create-auction" : r.name}`; }

function parseClaims(token?: string | null): JwtClaims | null {
  if (!token) return null;
  try {
    const [, p] = token.split("."); if (!p) return null;
    const json = atob(p.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(p.length / 4) * 4, "="));
    return JSON.parse(json) as JwtClaims;
  } catch { return null; }
}

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Черновик",
  PUBLISHED: "Опубликован",
  ACTIVE: "Активен",
  FINISHED: "Завершен",
  CLOSED: "Закрыт",
  CANCELED: "Отменен",
};

const ROLE_LABELS: Record<string, string> = {
  supplier: "Поставщик",
  buyer: "Заказчик",
  admin: "Администратор",
};

const money = (v: string | number | null | undefined) => v == null ? "-" : new Intl.NumberFormat("ru-RU", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(Number(v) || 0);
const dateText = (v?: string | null) => !v ? "-" : new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(v));
const statusText = (s?: string | null) => s ? (STATUS_LABELS[s] ?? s.replace(/_/g, " ")) : "-";
const roleText = (r?: string | null) => r ? (ROLE_LABELS[r] ?? r) : "-";
function timeLeft(v?: string | null, nowMs = Date.now()) {
  if (!v) return "-";
  const s = Math.floor((new Date(v).getTime() - nowMs) / 1000);
  if (s <= 0) return "Завершен";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h >= 24 ? `${Math.floor(h / 24)}д ${h % 24}ч осталось` : `${h}ч ${m}м осталось`;
}

function normalizeInnInput(value: string) {
  return value.replace(/\D/g, "").slice(0, 12);
}

function calcInnChecksum(digits: string, coefficients: number[]) {
  const total = coefficients.reduce((sum, coefficient, index) => sum + Number(digits[index]) * coefficient, 0);
  return (total % 11) % 10;
}

function isValidInn(inn: string) {
  if (!INN_REGEX.test(inn)) return false;
  if (inn.length === 10) {
    return calcInnChecksum(inn, [2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(inn[9]);
  }
  return (
    calcInnChecksum(inn, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(inn[10])
    && calcInnChecksum(inn, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(inn[11])
  );
}

function Card({ title, subtitle, action, children }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode }) {
  return <section className="mk-card"><div className="mk-card-head"><div><h3>{title}</h3>{subtitle ? <p>{subtitle}</p> : null}</div>{action ? <div>{action}</div> : null}</div>{children}</section>;
}
function Status({ s }: { s?: string }) { return <span className={`mk-status mk-status-${(s ?? "").toLowerCase()}`}>{statusText(s)}</span>; }
function Tile({
  a,
  open,
  nowMs,
  editAction,
}: {
  a: Auction;
  open: () => void;
  nowMs: number;
  editAction?: { onClick: () => void; label?: string };
}) {
  return (
    <div className="mk-auction-card-shell">
      <button type="button" className="mk-auction-card" onClick={open}>
        <div className="mk-product-media" aria-hidden="true"><div className="mk-product-badge">Реверс</div><div className="mk-product-icon">{(a.title || "A")[0].toUpperCase()}</div></div>
        <div className="mk-auction-head"><span className="mk-id">Лот</span><Status s={a.status} /></div>
        <h4>{a.title}</h4><p>{a.description || "Нет описания"}</p>
        <div className="mk-auction-meta"><span>{money(a.current_price ?? a.start_price)}</span><span>{timeLeft(a.end_date, nowMs)}</span></div>
      </button>
      {editAction ? (
        <div className="mk-card-inline-action">
          <button type="button" className="mk-ghost" onClick={editAction.onClick}>{editAction.label ?? "Редактировать"}</button>
        </div>
      ) : null}
    </div>
  );
}

function toLotInputs(lots: AuctionLot[] | undefined): AuctionLotInput[] {
  if (!lots?.length) return [];
  return lots.map((lot) => ({
    id: lot.id,
    quantity: String(lot.quantity ?? "1"),
  }));
}

function LotPicker({
  selectedLots,
  onChange,
  baseUrl,
  token,
  disabled,
}: {
  selectedLots: AuctionLotInput[];
  onChange: (lots: AuctionLotInput[]) => void;
  baseUrl: string;
  token?: string;
  disabled?: boolean;
}) {
  const [mode, setMode] = useState<"search" | "tree">("search");
  const [query, setQuery] = useState("");
  const [nodeId, setNodeId] = useState<number | undefined>(undefined);
  const [nodes, setNodes] = useState<CatalogNode[]>([]);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedDetails, setSelectedDetails] = useState<Record<number, CatalogItem>>({});
  const deferredQuery = useDeferredValue(query);
  const [catalogOpen, setCatalogOpen] = useState(false);

  useEffect(() => {
    let active = true;
    const loadNodes = async () => {
      const PAGE_SIZE = 500;
      const fetchNodePages = async (parentId?: number) => {
        const aggregated: CatalogNode[] = [];
        let offset = 0;
        while (true) {
          const page = await fetchCatalogNodes(
            {
              parent_id: parentId,
              limit: PAGE_SIZE,
              offset,
            },
            baseUrl,
            token,
          );
          aggregated.push(...page.results);
          if (page.results.length < PAGE_SIZE) break;
          offset += PAGE_SIZE;
        }
        return aggregated;
      };

      try {
        const byId = new Map<number, CatalogNode>();
        const queue: number[] = [];

        const roots = await fetchNodePages(undefined);
        roots.forEach((node) => {
          if (!byId.has(node.id)) {
            byId.set(node.id, node);
            queue.push(node.id);
          }
        });
        if (active) {
          // Show root categories immediately instead of waiting for full recursion.
          setNodes(Array.from(byId.values()));
        }

        // Load children for each discovered node because backend returns roots by default.
        while (queue.length) {
          const parentId = queue.shift();
          if (parentId == null) continue;
          let children: CatalogNode[];
          try {
            children = await fetchNodePages(parentId);
          } catch {
            // Skip failed branch but keep already loaded categories.
            continue;
          }
          children.forEach((node) => {
            if (byId.has(node.id)) return;
            byId.set(node.id, node);
            queue.push(node.id);
          });
        }

        if (active) setNodes(Array.from(byId.values()));
      } catch {
        if (active) setNodes((prev) => prev);
      }
    };
    void loadNodes();
    return () => {
      active = false;
    };
  }, [baseUrl, token]);

  useEffect(() => {
    let active = true;
    const loadItems = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await fetchCatalogItems(
          {
            q: mode === "search" ? deferredQuery.trim() : undefined,
            node_id: mode === "tree" ? nodeId : undefined,
            limit: 50,
          },
          baseUrl,
          token,
        );
        if (active) setItems(data.results);
      } catch (err) {
        if (!active) return;
        setItems([]);
        setError(toRussianErrorMessage(err));
      } finally {
        if (active) setLoading(false);
      }
    };
    void loadItems();
    return () => {
      active = false;
    };
  }, [baseUrl, token, deferredQuery, mode, nodeId]);

  useEffect(() => {
    let active = true;
    const loadSelected = async () => {
      const ids = selectedLots.map((lot) => lot.id);
      if (!ids.length) {
        setSelectedDetails({});
        return;
      }
      try {
        const resolved = await fetchCatalogItemsByIds(ids, baseUrl, token);
        if (!active) return;
        const byId: Record<number, CatalogItem> = {};
        resolved.forEach((item) => {
          byId[item.id] = item;
        });
        setSelectedDetails(byId);
      } catch {
        if (active) setSelectedDetails({});
      }
    };
    void loadSelected();
    return () => {
      active = false;
    };
  }, [selectedLots, baseUrl, token]);

  const selectedIds = useMemo(() => new Set(selectedLots.map((lot) => lot.id)), [selectedLots]);
  const nodeById = useMemo(() => {
    const map = new Map<number, CatalogNode>();
    nodes.forEach((node) => map.set(node.id, node));
    return map;
  }, [nodes]);
  const selectableNodes = useMemo(
    () => nodes.filter((node) => !node.has_children || node.items_count > 0),
    [nodes],
  );
  const categoryOptions = selectableNodes.length ? selectableNodes : nodes;

  function itemHierarchyText(item?: CatalogItem) {
    if (!item) return "";
    const node = nodeById.get(item.node_id);
    if (!node) return "";
    const parent = node.parent_id != null ? nodeById.get(node.parent_id) : undefined;
    const parentName = parent?.name?.trim() ? parent.name : "";
    if (node.name) return parentName ? `${parentName} -> ${node.name}` : node.name;
    return "";
  }

  function itemDisplayName(item?: CatalogItem) {
    if (!item) return "";
    const node = nodeById.get(item.node_id);
    if (!node?.name) return item.name;
    const normalizedItemName = (item.name ?? "").trim().toLowerCase();
    const normalizedNodeName = node.name.trim().toLowerCase();
    if (!normalizedItemName || normalizedItemName.includes(normalizedNodeName)) {
      return item.name;
    }
    return `${node.name} - ${item.name}`;
  }

  function addLot(item: CatalogItem) {
    if (selectedIds.has(item.id)) return;
    onChange([
      ...selectedLots,
      {
        id: item.id,
        quantity: item.default_quantity && item.default_quantity.trim() ? item.default_quantity : "1",
      },
    ]);
  }

  function removeLot(id: number) {
    onChange(selectedLots.filter((lot) => lot.id !== id));
  }

  function updateQty(id: number, quantity: string) {
    onChange(selectedLots.map((lot) => (lot.id === id ? { ...lot, quantity } : lot)));
  }

  return (
    <div className="mk-lot-picker">
      <div className="mk-subhead">
        <span>Каталог строительных материалов</span>
        <button
          type="button"
          className="mk-ghost"
          onClick={() => setCatalogOpen((value) => !value)}
          disabled={disabled}
        >
          {catalogOpen ? "Скрыть каталог" : "Открыть каталог"}
        </button>
      </div>

      {catalogOpen ? (
        <>
          <div className="mk-lot-picker-floating-backdrop" onClick={() => setCatalogOpen(false)} />
          <div className="mk-lot-picker-floating" role="dialog" aria-modal="true" aria-label="Каталог лотов">
            <div className="mk-subhead">
              <span>Подбор лотов</span>
              <button type="button" className="mk-ghost" onClick={() => setCatalogOpen(false)}>Закрыть</button>
            </div>
            <div className="mk-tabs">
              <button type="button" className={mode === "search" ? "mk-tab active" : "mk-tab"} onClick={() => setMode("search")}>Поиск</button>
              <button type="button" className={mode === "tree" ? "mk-tab active" : "mk-tab"} onClick={() => setMode("tree")}>Категория</button>
            </div>

            {mode === "search" ? (
              <label className="mk-field-label">Поиск лотов
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Код или наименование"
                  disabled={disabled}
                />
              </label>
            ) : (
              <label className="mk-field-label">Категория каталога
                <select
                  value={nodeId ?? ""}
                  onChange={(e) => setNodeId(e.target.value ? Number(e.target.value) : undefined)}
                  disabled={disabled}
                >
                  <option value="">Все конечные категории</option>
                  {categoryOptions.map((node) => (
                    <option key={node.id} value={node.id}>{node.name}</option>
                  ))}
                </select>
              </label>
            )}

            {mode === "tree" && nodeId !== undefined && !items.length && !loading && !error ? (
              <div className="mk-note">Для выбранной категории нет прямых позиций. Попробуйте другую конечную категорию.</div>
            ) : null}

            {error ? <div className="mk-warning">{error}</div> : null}
            {loading ? <div className="mk-empty small">Загрузка каталога...</div> : null}
            {!loading && !items.length ? <div className="mk-empty small">Позиции не найдены.</div> : null}
            {!!items.length ? (
              <div className="mk-catalog-items">
                {items.map((item) => (
                  <div key={item.id} className="mk-catalog-row">
                    <div>
                      <strong>{itemDisplayName(item)}</strong>
                      <span>{item.code} · {item.unit}</span>
                      {itemHierarchyText(item) ? <span>{itemHierarchyText(item)}</span> : null}
                    </div>
                    <button type="button" className="mk-ghost" onClick={() => addLot(item)} disabled={disabled || selectedIds.has(item.id)}>
                      {selectedIds.has(item.id) ? "Добавлен" : "Добавить"}
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      <div className="mk-subhead"><span>Выбранные лоты</span><small>{selectedLots.length}</small></div>
      {!selectedLots.length ? <div className="mk-empty small">Выберите минимум один лот.</div> : null}
      {!!selectedLots.length ? (
        <div className="mk-selected-lots">
          {selectedLots.map((lot) => {
            const item = selectedDetails[lot.id];
            return (
              <div key={lot.id} className="mk-selected-lot-row">
                <div>
                  <strong>{item ? itemDisplayName(item) : `Позиция #${lot.id}`}</strong>
                  <span>{item?.code ?? "Код отсутствует"}</span>
                  {itemHierarchyText(item) ? <span>{itemHierarchyText(item)}</span> : null}
                </div>
                <div className="mk-selected-lot-controls">
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={lot.quantity}
                    onChange={(e) => updateQty(lot.id, e.target.value)}
                    disabled={disabled}
                  />
                  <button type="button" className="mk-ghost" onClick={() => removeLot(lot.id)} disabled={disabled}>Удалить</button>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [apiBase] = useState(getStoredApiBase());
  const [tokens, setTokens] = useState<TokenPair | null>(getStoredTokens());
  const [toast, setToast] = useState<Toast>(null);
  const [clockNowMs, setClockNowMs] = useState(() => Date.now());
  const [serverOffsetMs, setServerOffsetMs] = useState(0);
  const [query, setQuery] = useState("");
  const dq = useDeferredValue(query);
  const [catalogMode, setCatalogMode] = useState<"all" | "active">("all");
  const [detailTab, setDetailTab] = useState<"overview" | "bids">("overview");
  const [allAuctions, setAllAuctions] = useState<Auction[]>([]);
  const [activeAuctions, setActiveAuctions] = useState<Auction[]>([]);
  const [loadingAuctions, setLoadingAuctions] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(route.name === "auction" ? route.id : null);
  const [auction, setAuction] = useState<Auction | null>(null);
  const [loadingAuction, setLoadingAuction] = useState(false);
  const [bids, setBids] = useState<Bid[]>([]);
  const [bidsMsg, setBidsMsg] = useState("");
  const [loadingBids, setLoadingBids] = useState(false);
  const [winner, setWinner] = useState<Bid | null>(null);
  const [winnerMsg, setWinnerMsg] = useState("");
  const [loadingWinner, setLoadingWinner] = useState(false);
  const [bidForm, setBidForm] = useState({ bid_amount: "", comment: "" });
  const [bidLoading, setBidLoading] = useState(false);
  const [draftEditForm, setDraftEditForm] = useState<DraftEditForm>(DEFAULT_DRAFT_EDIT_FORM);
  const [draftEditLoading, setDraftEditLoading] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">(route.name === "register" ? "register" : "login");
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [registerForm, setRegisterForm] = useState<RegisterPayload>({ username: "", email: "", password: "", role: "supplier", company_name: "", inn: "" });
  const [registerInnLoading, setRegisterInnLoading] = useState(false);
  const [registerInnError, setRegisterInnError] = useState("");
  const [registerInnResolved, setRegisterInnResolved] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [createForm, setCreateForm] = useState<CreateForm>(DEFAULT_CREATE);
  const [createLots, setCreateLots] = useState<AuctionLotInput[]>([]);
  const [createLotErrors, setCreateLotErrors] = useState<string[]>([]);
  const [createLoading, setCreateLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [currentUserLoading, setCurrentUserLoading] = useState(false);
  const [ownedAuctions, setOwnedAuctions] = useState<Auction[]>([]);
  const [ownedAuctionsLoading, setOwnedAuctionsLoading] = useState(false);
  const [participatingAuctions, setParticipatingAuctions] = useState<Auction[]>([]);
  const [participatingLoading, setParticipatingLoading] = useState(false);
  const [accountForm, setAccountForm] = useState<AccountForm>(DEFAULT_ACCOUNT_FORM);
  const [accountInnLoading, setAccountInnLoading] = useState(false);
  const [accountInnError, setAccountInnError] = useState("");
  const [accountInnResolved, setAccountInnResolved] = useState("");
  const [accountSaving, setAccountSaving] = useState(false);
  const [draftLots, setDraftLots] = useState<AuctionLotInput[]>([]);
  const [draftLotErrors, setDraftLotErrors] = useState<string[]>([]);
  const claims = parseClaims(tokens?.access);
  const tokenUserId =
    typeof claims?.user_id === "number"
      ? claims.user_id
      : (typeof claims?.user_id === "string" && claims.user_id.trim() ? Number(claims.user_id) : undefined);
  const userId = Number.isFinite(tokenUserId) ? tokenUserId : (typeof currentUser?.id === "number" ? currentUser.id : undefined);
  const serverNowMs = clockNowMs + serverOffsetMs;

  function go(next: Route) { window.history.pushState(null, "", routePath(next)); setRoute(next); }
  function openAuction(id: number) { setSelectedId(id); go({ name: "auction", id }); }

  useEffect(() => {
    const pop = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (route.name === "auction") setSelectedId(route.id);
    if (route.name === "login") setAuthMode("login");
    if (route.name === "register") setAuthMode("register");
  }, [route]);
  useEffect(() => {
    if (route.name === "account" && !tokens?.access) {
      go({ name: "login" });
    }
  }, [route, tokens?.access]);
  useEffect(() => { if (!toast) return; const t = window.setTimeout(() => setToast(null), 3200); return () => window.clearTimeout(t); }, [toast]);
  useEffect(() => {
    const t = window.setInterval(() => setClockNowMs(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  async function syncServerTime() {
    try {
      const data = await fetchServerTime(apiBase);
      setServerOffsetMs(data.server_time_ms - Date.now());
    } catch {
      // Keep local clock if server-time endpoint is temporarily unavailable.
    }
  }

  async function loadCurrentUser(token: string) {
    setCurrentUserLoading(true);
    try {
      setCurrentUser(await fetchCurrentUser(token, apiBase));
    } catch {
      setCurrentUser(null);
    } finally {
      setCurrentUserLoading(false);
    }
  }
  async function loadOwnedAuctions(token: string) {
    setOwnedAuctionsLoading(true);
    try {
      const data = await fetchMyAuctions(token, apiBase);
      setOwnedAuctions(data.map(normalizeAuction));
    } catch {
      setOwnedAuctions([]);
    } finally {
      setOwnedAuctionsLoading(false);
    }
  }
  async function loadParticipatingAuctions(token: string) {
    setParticipatingLoading(true);
    try {
      const data = await fetchMyParticipatingAuctions(token, apiBase);
      setParticipatingAuctions(data.map(normalizeAuction));
    } catch {
      setParticipatingAuctions([]);
    } finally {
      setParticipatingLoading(false);
    }
  }

  async function refreshAuctions() {
    setLoadingAuctions(true);
    try {
      const [all, active] = await Promise.all([fetchAuctions(apiBase, tokens?.access ?? undefined), fetchActiveAuctions(apiBase)]);
      const allN = all.map(normalizeAuction); const activeN = active.map(normalizeAuction);
      setAllAuctions(allN); setActiveAuctions(activeN);
      if (!selectedId && activeN[0]) setSelectedId(activeN[0].id);
    } catch (e) { setToast({ kind: "error", text: `Не удалось загрузить аукционы: ${toRussianErrorMessage(e)}` }); }
    finally { setLoadingAuctions(false); }
  }
  async function loadAuction(id: number, silent = false) {
    if (!silent) setLoadingAuction(true);
    try { setAuction(normalizeAuction(await fetchAuction(id, apiBase, tokens?.access ?? undefined))); }
    catch (e) { setAuction(null); setToast({ kind: "error", text: `Не удалось загрузить аукцион: ${toRussianErrorMessage(e)}` }); }
    finally { if (!silent) setLoadingAuction(false); }
  }
  async function loadBids(id: number) {
    if (!tokens?.access) { setBids([]); setBidsMsg("Войдите, чтобы посмотреть историю ставок."); return; }
    setLoadingBids(true); setBidsMsg("");
    try { const data = await fetchAuctionBids(id, tokens.access, apiBase); setBids(data); if (!data.length) setBidsMsg("Ставок пока нет."); }
    catch (e) { setBids([]); setBidsMsg(toRussianErrorMessage(e)); }
    finally { setLoadingBids(false); }
  }
  async function loadWinner(id: number) {
    if (!tokens?.access) { setWinner(null); setWinnerMsg("Войдите, чтобы проверить победителя."); return; }
    setLoadingWinner(true); setWinnerMsg("");
    try { setWinner(await fetchAuctionWinner(id, tokens.access, apiBase)); }
    catch (e) { setWinner(null); setWinnerMsg(toRussianErrorMessage(e)); }
    finally { setLoadingWinner(false); }
  }

  useEffect(() => {
    void syncServerTime();
    void refreshAuctions();
    const t = window.setInterval(() => { void syncServerTime(); void refreshAuctions(); if (selectedId) void loadAuction(selectedId, true); }, 10000);
    return () => window.clearInterval(t);
  }, [apiBase, selectedId]);
  useEffect(() => {
    if (!tokens?.access) {
      setCurrentUser(null);
      setCurrentUserLoading(false);
      setAccountForm(DEFAULT_ACCOUNT_FORM);
      setOwnedAuctions([]);
      setOwnedAuctionsLoading(false);
      setParticipatingAuctions([]);
      setParticipatingLoading(false);
      return;
    }
    void loadCurrentUser(tokens.access);
    void loadOwnedAuctions(tokens.access);
    void loadParticipatingAuctions(tokens.access);
  }, [tokens?.access, apiBase]);
  useEffect(() => {
    if (!currentUser) return;
    setAccountForm({
      username: currentUser.username ?? "",
      email: currentUser.email ?? "",
      role: (currentUser.profile?.role as UserRole | undefined) ?? "supplier",
      company_name: currentUser.profile?.company_name ?? "",
      inn: currentUser.profile?.inn ?? "",
      password: "",
    });
  }, [currentUser]);
  useEffect(() => {
    if (!auction) {
      setDraftEditForm(DEFAULT_DRAFT_EDIT_FORM);
      setDraftLots([]);
      setDraftLotErrors([]);
      return;
    }
    setDraftEditForm({
      title: auction.title ?? "",
      description: auction.description ?? "",
      start_price: String(auction.start_price ?? ""),
      min_bid_decrement: String(auction.specific?.min_bid_decrement ?? ""),
      start_date_local: auction.start_date ? new Date(auction.start_date).toISOString().slice(0, 16) : "",
      end_date_local: auction.end_date ? new Date(auction.end_date).toISOString().slice(0, 16) : "",
    });
    setDraftLots(toLotInputs(auction.lots));
    setDraftLotErrors([]);
  }, [auction?.id, auction?.title, auction?.description, auction?.start_price, auction?.start_date, auction?.end_date, auction?.specific?.min_bid_decrement]);
  useEffect(() => { if (!selectedId) return; startTransition(() => { void loadAuction(selectedId); }); }, [selectedId, apiBase]);
  useEffect(() => { if (route.name === "auction" && detailTab === "bids" && selectedId) void loadBids(selectedId); }, [route, detailTab, selectedId, apiBase, tokens?.access]);
  useEffect(() => {
    const inn = normalizeInnInput(registerForm.inn ?? "");
    if (!inn) {
      setRegisterInnError("");
      setRegisterInnResolved("");
      return;
    }
    if (!INN_REGEX.test(inn)) {
      setRegisterInnError("ИНН должен содержать 10 или 12 цифр.");
      setRegisterInnResolved("");
      return;
    }
    if (!isValidInn(inn)) {
      setRegisterInnError("Введите корректный ИНН.");
      setRegisterInnResolved("");
      return;
    }
    const timer = window.setTimeout(() => {
      void (async () => {
        setRegisterInnLoading(true);
        setRegisterInnError("");
        try {
          const party = await fetchPartyByInn(inn, apiBase);
          setRegisterInnResolved(party.company_name);
          setRegisterForm((form) => ({ ...form, company_name: party.company_name, inn }));
        } catch (err) {
          setRegisterInnResolved("");
          setRegisterInnError(toRussianErrorMessage(err));
        } finally {
          setRegisterInnLoading(false);
        }
      })();
    }, 500);
    return () => window.clearTimeout(timer);
  }, [registerForm.inn, apiBase]);
  useEffect(() => {
    const inn = normalizeInnInput(accountForm.inn);
    if (!inn) {
      setAccountInnError("");
      setAccountInnResolved("");
      return;
    }
    if (!INN_REGEX.test(inn)) {
      setAccountInnError("ИНН должен содержать 10 или 12 цифр.");
      setAccountInnResolved("");
      return;
    }
    if (!isValidInn(inn)) {
      setAccountInnError("Введите корректный ИНН.");
      setAccountInnResolved("");
      return;
    }
    const timer = window.setTimeout(() => {
      void (async () => {
        setAccountInnLoading(true);
        setAccountInnError("");
        try {
          const party = await fetchPartyByInn(inn, apiBase);
          setAccountInnResolved(party.company_name);
          setAccountForm((form) => ({ ...form, company_name: party.company_name, inn }));
        } catch (err) {
          setAccountInnResolved("");
          setAccountInnError(toRussianErrorMessage(err));
        } finally {
          setAccountInnLoading(false);
        }
      })();
    }, 500);
    return () => window.clearTimeout(timer);
  }, [accountForm.inn, apiBase]);

  const source = catalogMode === "active" ? activeAuctions : allAuctions;
  const filtered = useMemo(() => {
    const q = dq.trim().toLowerCase(); if (!q) return source;
    return source.filter((a) => `${a.id} ${a.title} ${a.description} ${a.status}`.toLowerCase().includes(q));
  }, [source, dq]);
  const myAuctions = ownedAuctions;
  const liveHome = activeAuctions.slice(0, 8);
  const endingSoon = [...activeAuctions].sort((a, b) => new Date(a.end_date).getTime() - new Date(b.end_date).getTime()).slice(0, 4);

  async function onLogin(e: FormEvent) {
    e.preventDefault(); setAuthLoading(true);
    try { const pair = await loginUser(loginForm.username, loginForm.password, apiBase); setStoredTokens(pair); setTokens(pair); setToast({ kind: "ok", text: "Вход выполнен." }); go({ name: "account" }); }
    catch (err) { setToast({ kind: "error", text: `Ошибка входа: ${toRussianErrorMessage(err)}` }); }
    finally { setAuthLoading(false); }
  }
  async function onRegister(e: FormEvent) {
    e.preventDefault(); setAuthLoading(true);
    const normalizedInn = normalizeInnInput(registerForm.inn ?? "");
    if (normalizedInn && !isValidInn(normalizedInn)) {
      setAuthLoading(false);
      setToast({ kind: "error", text: "Введите корректный ИНН." });
      return;
    }
    try { const res = await registerUser({ ...registerForm, role: registerForm.role === "admin" ? "supplier" : registerForm.role }, apiBase); setLoginForm((f) => ({ ...f, username: res.username })); setToast({ kind: "ok", text: `Аккаунт создан: ${res.username}.` }); go({ name: "login" }); }
    catch (err) { setToast({ kind: "error", text: `Ошибка регистрации: ${toRussianErrorMessage(err)}` }); }
    finally { setAuthLoading(false); }
  }
  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!tokens?.access) { setToast({ kind: "error", text: "Сначала войдите в аккаунт, чтобы создать аукцион." }); return; }
    const lotsValidation = validateAuctionLots(createLots);
    if (lotsValidation.errors.length) {
      setCreateLotErrors(lotsValidation.errors);
      setToast({ kind: "error", text: lotsValidation.errors[0] });
      return;
    }
    setCreateLotErrors([]);
    const payload: AuctionCreatePayload = {
      title: createForm.title,
      description: createForm.description,
      start_price: Number(createForm.start_price),
      start_date: new Date(createForm.start_date_local).toISOString(),
      end_date: new Date(createForm.end_date_local).toISOString(),
      auction_type: "reverseenglishauction",
      min_bid_decrement: Number(createForm.min_bid_decrement),
      lots: lotsValidation.normalizedLots,
    };
    setCreateLoading(true);
    try { const created = normalizeAuction(await createAuction(payload, tokens.access, apiBase)); setCreateForm(DEFAULT_CREATE); setCreateLots([]); setToast({ kind: "ok", text: `Аукцион создан.` }); await refreshAuctions(); await loadOwnedAuctions(tokens.access); openAuction(created.id); }
    catch (err) { setToast({ kind: "error", text: `Ошибка создания: ${toRussianErrorMessage(err)}` }); }
    finally { setCreateLoading(false); }
  }
  async function onBid(e: FormEvent) {
    e.preventDefault(); if (!auction) return;
    if (!tokens?.access) { setToast({ kind: "error", text: "Сначала войдите в аккаунт, чтобы сделать ставку." }); go({ name: "login" }); return; }
    setBidLoading(true);
    try { const result = await submitBid(auction.id, tokens.access, bidForm, apiBase); window.location.href = result.redirect_url; }
    catch (err) { setToast({ kind: "error", text: `Ошибка ставки: ${toRussianErrorMessage(err)}` }); }
    finally { setBidLoading(false); }
  }
  async function onSaveAccount(e: FormEvent) {
    e.preventDefault();
    if (!tokens?.access) {
      setToast({ kind: "error", text: "Сначала войдите в аккаунт." });
      return;
    }
    const normalizedInn = normalizeInnInput(accountForm.inn);
    if (normalizedInn && !isValidInn(normalizedInn)) {
      setToast({ kind: "error", text: "Введите корректный ИНН." });
      return;
    }
    const payload: CurrentUserUpdatePayload = {
      username: accountForm.username.trim(),
      role: accountForm.role,
      company_name: accountForm.company_name,
      inn: normalizedInn,
    };
    if (accountForm.password.trim()) payload.password = accountForm.password;

    setAccountSaving(true);
    try {
      const updated = await updateCurrentUser(payload, tokens.access, apiBase);
      setCurrentUser(updated);
      setAccountForm((f) => ({ ...f, password: "" }));
      setToast({ kind: "ok", text: "Данные аккаунта обновлены." });
    } catch (err) {
      setToast({ kind: "error", text: `Ошибка обновления: ${toRussianErrorMessage(err)}` });
    } finally {
      setAccountSaving(false);
    }
  }
  async function onSaveDraft() {
    if (!auction || !tokens?.access) {
      setToast({ kind: "error", text: "Сначала войдите в аккаунт." });
      return;
    }
    const lotsValidation = validateAuctionLots(draftLots);
    if (lotsValidation.errors.length) {
      setDraftLotErrors(lotsValidation.errors);
      setToast({ kind: "error", text: lotsValidation.errors[0] });
      return;
    }
    setDraftLotErrors([]);
    setDraftEditLoading(true);
    try {
      const updated = await updateAuction(
        auction.id,
        {
          title: draftEditForm.title,
          description: draftEditForm.description,
          start_price: Number(draftEditForm.start_price),
          start_date: new Date(draftEditForm.start_date_local).toISOString(),
          end_date: new Date(draftEditForm.end_date_local).toISOString(),
          auction_type: "reverseenglishauction",
          min_bid_decrement: Number(draftEditForm.min_bid_decrement),
          lots: lotsValidation.normalizedLots,
        },
        tokens.access,
        apiBase,
      );
      const normalized = normalizeAuction(updated);
      setAuction(normalized);
      await refreshAuctions();
      await loadOwnedAuctions(tokens.access);
      setToast({ kind: "ok", text: "Черновик сохранен." });
    } catch (err) {
      setToast({ kind: "error", text: `Ошибка сохранения: ${toRussianErrorMessage(err)}` });
    } finally {
      setDraftEditLoading(false);
    }
  }
  async function onPublish() {
    if (!auction || !tokens?.access) {
      setToast({ kind: "error", text: "Сначала войдите в аккаунт." });
      return;
    }
    const lotsValidation = validateAuctionLots(draftLots);
    if (lotsValidation.errors.length) {
      setDraftLotErrors(lotsValidation.errors);
      setToast({ kind: "error", text: "Перед публикацией добавьте минимум один лот." });
      return;
    }
    setDraftEditLoading(true);
    try {
      const { redirect_url } = await publishAuction(auction.id, tokens.access, apiBase);
      window.location.href = redirect_url;
    } catch (err) {
      setToast({ kind: "error", text: `Ошибка публикации: ${toRussianErrorMessage(err)}` });
      setDraftEditLoading(false);
    }
  }
  async function onCloseAuction() {
    if (!auction || !tokens?.access) {
      setToast({ kind: "error", text: "Сначала войдите в аккаунт." });
      return;
    }
    const confirmed = window.confirm(`Закрыть аукцион "${auction.title}"? После этого он будет закрыт для участников.`);
    if (!confirmed) return;
    try {
      const updated = normalizeAuction(await closeAuction(auction.id, tokens.access, apiBase));
      setAuction(updated);
      await refreshAuctions();
      await loadOwnedAuctions(tokens.access);
      setToast({ kind: "ok", text: "Аукцион закрыт." });
    } catch (err) {
      setToast({ kind: "error", text: `Ошибка закрытия: ${toRussianErrorMessage(err)}` });
    }
  }

  const navActive = (name: Route["name"]) => route.name === name || (name === "browse" && route.name === "auction");
  const isAuctionOwner = !!auction && typeof userId === "number" && Number(auction.owner) === Number(userId);
  const isOwnerDraft = !!auction && isAuctionOwner && auction.status === "DRAFT";
  const canOwnerCloseAuction = !!auction && isAuctionOwner && !["CLOSED", "FINISHED", "CANCELED"].includes(auction.status);
  const viewerRole = currentUser?.profile?.role;
  const canBidByRole = viewerRole === "supplier" || viewerRole === "admin";

  return (
    <div className="mk-shell">
      <header className="mk-topbar mk-topbar-market">
        <button type="button" className="mk-brand mk-brand-btn" onClick={() => go({ name: "home" })}><div className="mk-logo">BF</div><div><strong>Bidfall Маркет</strong><span>Активные аукционы</span></div></button>
        <div className="mk-searchbar mk-searchbar-market"><input placeholder="Поиск аукционов по названию, ID или статусу" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") go({ name: "browse" }); }} /><button type="button" onClick={() => go({ name: "browse" })}>Поиск</button></div>
        <nav className="mk-nav"><button type="button" className={navActive("home") ? "mk-pill active" : "mk-pill"} onClick={() => go({ name: "home" })}>Главная</button><button type="button" className={navActive("browse") ? "mk-pill active" : "mk-pill"} onClick={() => go({ name: "browse" })}>Аукционы</button><button type="button" className={navActive("sell") ? "mk-pill active" : "mk-pill"} onClick={() => go({ name: "sell" })}>Создать аукцион</button>{tokens?.access ? <button type="button" className={navActive("account") ? "mk-pill active" : "mk-pill"} onClick={() => go({ name: "account" })}>Аккаунт</button> : null}{!tokens?.access ? <button type="button" className={route.name === "login" || route.name === "register" ? "mk-pill active" : "mk-pill"} onClick={() => go({ name: "login" })}>Войти</button> : null}</nav>
      </header>

      {route.name === "home" ? <>
        <Card title="Идущие сейчас аукционы" subtitle="Аукционы, которые идут прямо сейчас." action={<button type="button" className="mk-ghost" onClick={() => go({ name: "browse" })}>Показать все</button>}>
          {loadingAuctions ? <div className="mk-empty">Загрузка аукционов...</div> : null}
          {!loadingAuctions && !liveHome.length ? <div className="mk-empty">Сейчас нет активных аукционов.</div> : null}
          {!!liveHome.length ? <div className="mk-grid mk-grid-market">{liveHome.map((a) => <Tile key={a.id} a={a} nowMs={serverNowMs} open={() => openAuction(a.id)} />)}</div> : null}
        </Card>
        <Card title="Скоро завершатся" subtitle="Быстрый доступ к аукционам, которые закроются первыми."><div className="mk-list-rows">{endingSoon.map((a) => <button key={a.id} type="button" className="mk-row-link" onClick={() => openAuction(a.id)}><div><strong>{a.title}</strong><span>{statusText(a.status)}</span></div><div><strong>{money(a.current_price ?? a.start_price)}</strong><span>{timeLeft(a.end_date, serverNowMs)}</span></div></button>)}{!endingSoon.length ? <div className="mk-empty small">Активных аукционов пока нет.</div> : null}</div></Card>
      </> : null}

      {route.name === "browse" ? <div className="mk-page-grid"><aside className="mk-page-sidebar"><Card title="Фильтры" subtitle="Параметры отображения списка аукционов."><div className="mk-filter-block"><div className="mk-tabs"><button type="button" className={catalogMode === "all" ? "mk-tab active" : "mk-tab"} onClick={() => setCatalogMode("all")}>Все</button><button type="button" className={catalogMode === "active" ? "mk-tab active" : "mk-tab"} onClick={() => setCatalogMode("active")}>Идут сейчас</button></div><label className="mk-field-label">Поиск<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Название аукциона, статус, ID" /></label><div className="mk-note">{filtered.length} объявлений</div></div></Card></aside><section className="mk-page-content"><Card title="Список аукционов" subtitle="Просмотр всех аукционов в формате витрины." action={loadingAuctions ? <small className="mk-inline-muted">Обновление...</small> : undefined}>{loadingAuctions && !filtered.length ? <div className="mk-empty">Загрузка аукционов...</div> : null}{!loadingAuctions && !filtered.length ? <div className="mk-empty">По вашему запросу ничего не найдено.</div> : null}{!!filtered.length ? <div className="mk-grid mk-grid-market">{filtered.map((a) => <Tile key={a.id} a={a} nowMs={serverNowMs} open={() => openAuction(a.id)} />)}</div> : null}</Card></section></div> : null}

      {route.name === "auction" ? <div className="mk-detail-layout"><section className="mk-detail-main"><Card title={auction?.title || "Аукцион"} subtitle={auction ? `Активный аукцион` : "Выберите аукцион из списка."} action={auction ? <Status s={auction.status} /> : undefined}>{loadingAuction ? <div className="mk-empty">Загрузка аукциона...</div> : null}{!loadingAuction && !auction ? <div className="mk-empty">Аукцион не найден.</div> : null}{auction ? <div className="mk-detail"><div className="mk-product-hero"><div className="mk-product-gallery" aria-hidden="true"><div className="mk-product-gallery-main">{(auction.title || "А")[0].toUpperCase()}</div><div className="mk-product-gallery-row"><span /><span /><span /></div></div><div className="mk-product-summary"><p className="mk-product-copy">{auction.description || "Описание отсутствует."}</p><div className="mk-detail-stats"><div><small>Текущая цена</small><strong>{money(auction.current_price ?? auction.start_price)}</strong></div><div><small>Начальная цена</small><strong>{money(auction.start_price)}</strong></div><div><small>До окончания</small><strong>{timeLeft(auction.end_date, serverNowMs)}</strong></div><div><small>Мин. шаг снижения</small><strong>{auction.specific?.min_bid_decrement ?? "-"}</strong></div></div><div className="mk-meta-list"><span>Начало: {dateText(auction.start_date)}</span><span>Окончание: {dateText(auction.end_date)}</span><span>Продавец</span></div></div></div><div className="mk-tabs compact mk-segmented"><button type="button" className={detailTab === "overview" ? "mk-tab active" : "mk-tab"} onClick={() => setDetailTab("overview")}>Обзор</button><button type="button" className={detailTab === "bids" ? "mk-tab active" : "mk-tab"} onClick={() => { setDetailTab("bids"); void loadBids(auction.id); }}>Ставки</button></div>{detailTab === "overview" ? <div className="mk-lots"><div className="mk-subhead"><span>Лоты</span><small>{auction.lots?.length ?? 0}</small></div>{(auction.lots ?? []).map((lot) => <div key={`${lot.id}-${lot.code}`} className="mk-lot-row"><div><strong>{lot.name}</strong><span>{lot.code || "Позиция"}</span></div><div><strong>{lot.quantity}</strong><span>{lot.unit}</span></div></div>)}{!auction.lots?.length ? <div className="mk-empty small">Лоты пока не добавлены.</div> : null}</div> : <div className="mk-bids">{bidsMsg ? <div className="mk-warning">{bidsMsg}</div> : null}{loadingBids ? <div className="mk-empty small">Загрузка ставок...</div> : null}{!loadingBids && bids.map((b) => <div key={b.id} className="mk-bid-row"><div><strong>{money(b.bid)}</strong><span>Поставщик</span></div><p>{b.comment || "Без комментария"}</p></div>)}{!loadingBids && !bids.length && !bidsMsg ? <div className="mk-empty small">Ставок пока нет.</div> : null}</div>}</div> : null}</Card></section><aside className="mk-detail-side"><Card title={isOwnerDraft ? "Редактирование черновика" : "Сделать ставку"} subtitle={isOwnerDraft ? "Редактировать можно только черновики. Когда все готово, опубликуйте аукцион." : "Отправьте новую ставку для этого аукциона."}>{!auction ? <div className="mk-empty small">Сначала выберите аукцион.</div> : isOwnerDraft ? <div className="mk-form"><div className="mk-form-grid"><label className="mk-field-label">Название<input value={draftEditForm.title} onChange={(e) => setDraftEditForm((f) => ({ ...f, title: e.target.value }))} /></label><label className="mk-field-label">Начальная цена<input type="number" step="0.01" value={draftEditForm.start_price} onChange={(e) => setDraftEditForm((f) => ({ ...f, start_price: e.target.value }))} /></label><label className="mk-field-label">Время начала<input type="datetime-local" value={draftEditForm.start_date_local} onChange={(e) => setDraftEditForm((f) => ({ ...f, start_date_local: e.target.value }))} /></label><label className="mk-field-label">Время окончания<input type="datetime-local" value={draftEditForm.end_date_local} onChange={(e) => setDraftEditForm((f) => ({ ...f, end_date_local: e.target.value }))} /></label><label className="mk-field-label">Мин. шаг снижения<input type="number" step="0.01" value={draftEditForm.min_bid_decrement} onChange={(e) => setDraftEditForm((f) => ({ ...f, min_bid_decrement: e.target.value }))} /></label></div><label className="mk-field-label">Описание<textarea rows={4} value={draftEditForm.description} onChange={(e) => setDraftEditForm((f) => ({ ...f, description: e.target.value }))} /></label><LotPicker selectedLots={draftLots} onChange={setDraftLots} baseUrl={apiBase} token={tokens?.access ?? undefined} disabled={draftEditLoading} />{draftLotErrors.length ? <div className="mk-warning">{draftLotErrors.join("; ")}</div> : null}<div className="mk-inline-actions"><button type="button" disabled={draftEditLoading} onClick={onSaveDraft}>{draftEditLoading ? "Сохранение..." : "Сохранить черновик"}</button><button type="button" className="mk-ghost" disabled={draftEditLoading} onClick={onPublish}>{draftEditLoading ? "Подождите..." : "Опубликовать"}</button>{canOwnerCloseAuction ? <button type="button" className="mk-ghost" disabled={draftEditLoading} onClick={() => void onCloseAuction()}>{draftEditLoading ? "Подождите..." : "Закрыть аукцион"}</button> : null}</div></div> : isAuctionOwner ? <div className="mk-empty small">Этот аукцион уже опубликован. Владелец не может редактировать его или делать ставки.</div> : !tokens?.access ? <div className="mk-empty small">Войдите как поставщик, чтобы делать ставки.</div> : !canBidByRole ? <div className="mk-empty small">Ставки в этом аукционе могут делать только поставщики.</div> : auction.status !== "ACTIVE" ? <div className="mk-empty small">Прием ставок начнется, когда аукцион станет активным.</div> : <form className="mk-form" onSubmit={onBid}><label className="mk-field-label">Цена ставки (чем ниже, тем лучше)<input type="number" step="0.01" min="0" value={bidForm.bid_amount} onChange={(e) => setBidForm((f) => ({ ...f, bid_amount: e.target.value }))} placeholder="Введите более низкую цену" /></label><label className="mk-field-label">Комментарий (необязательно)<input value={bidForm.comment} onChange={(e) => setBidForm((f) => ({ ...f, comment: e.target.value }))} placeholder="Срок поставки, примечания" /></label><div className="mk-inline-actions"><button type="submit" disabled={bidLoading}>{bidLoading ? "Отправка..." : "Отправить ставку"}</button><button type="button" className="mk-ghost" onClick={() => void loadBids(auction.id)}>Обновить ставки</button><button type="button" className="mk-ghost" onClick={() => void loadWinner(auction.id)}>Проверить победителя</button></div>{(loadingWinner || winner || winnerMsg) ? <div className="mk-winner-box">{loadingWinner ? <span>Проверка победителя...</span> : null}{winner ? <span>Текущий победитель: {money(winner.bid)}</span> : null}{!winner && winnerMsg ? <span>{winnerMsg}</span> : null}</div> : null}</form>}</Card>{isAuctionOwner && !isOwnerDraft && canOwnerCloseAuction ? <Card title="Действия владельца" subtitle="Управление статусом аукциона."><div className="mk-inline-actions"><button type="button" className="mk-ghost" onClick={() => void onCloseAuction()}>Закрыть аукцион</button></div></Card> : null}<Card title="Другие аукционы" subtitle="Откройте другой активный или недавний аукцион."><div className="mk-list-rows">{(activeAuctions.length ? activeAuctions : allAuctions).slice(0, 6).map((a) => <button key={a.id} type="button" className="mk-row-link" onClick={() => openAuction(a.id)}><div><strong>{a.title}</strong><span>{statusText(a.status)}</span></div><div><strong>{money(a.current_price ?? a.start_price)}</strong><span>{timeLeft(a.end_date, serverNowMs)}</span></div></button>)}{!(activeAuctions.length || allAuctions.length) ? <div className="mk-empty small">Нет доступных аукционов.</div> : null}</div></Card></aside></div> : null}

      {route.name === "sell" ? (
        <div className="mk-create-page-full">
          {!tokens?.access ? (
            <Card title="Нужен вход" subtitle="Чтобы создать аукцион, войдите в аккаунт.">
              <div className="mk-warning">Вы не авторизованы.</div>
              <div className="mk-inline-actions">
                <button type="button" onClick={() => go({ name: "login" })}>Перейти ко входу</button>
                <button type="button" className="mk-ghost" onClick={() => go({ name: "home" })}>На главную</button>
              </div>
            </Card>
          ) : (
            <Card title="Создать аукцион" subtitle="Заполните параметры аукциона. Можно сохранить черновик или опубликовать.">
              <form className="mk-form" onSubmit={onCreate}>
                <div className="mk-form-grid">
                  <label className="mk-field-label">Название аукциона<input value={createForm.title} onChange={(e) => setCreateForm((f) => ({ ...f, title: e.target.value }))} placeholder="Например: закупка расходных материалов" /></label>
                  <label className="mk-field-label">Начальная цена<input type="number" step="0.01" value={createForm.start_price} onChange={(e) => setCreateForm((f) => ({ ...f, start_price: e.target.value }))} /></label>
                  <label className="mk-field-label">Время начала<input type="datetime-local" value={createForm.start_date_local} onChange={(e) => setCreateForm((f) => ({ ...f, start_date_local: e.target.value }))} /></label>
                  <label className="mk-field-label">Время окончания<input type="datetime-local" value={createForm.end_date_local} onChange={(e) => setCreateForm((f) => ({ ...f, end_date_local: e.target.value }))} /></label>
                  <label className="mk-field-label">Мин. шаг снижения<input type="number" step="0.01" value={createForm.min_bid_decrement} onChange={(e) => setCreateForm((f) => ({ ...f, min_bid_decrement: e.target.value }))} /></label>
                  <label className="mk-field-label">Тип аукциона<input value="Реверсный аукцион" readOnly /></label>
                </div>
                <label className="mk-field-label">Описание<textarea rows={4} value={createForm.description} onChange={(e) => setCreateForm((f) => ({ ...f, description: e.target.value }))} placeholder="Условия поставки, требования к участникам, комментарии" /></label>
                <LotPicker selectedLots={createLots} onChange={setCreateLots} baseUrl={apiBase} token={tokens?.access ?? undefined} disabled={createLoading} />
                {createLotErrors.length ? <div className="mk-warning">{createLotErrors.join("; ")}</div> : null}
                <div className="mk-inline-actions">
                  <button type="submit" disabled={createLoading}>{createLoading ? "Сохранение..." : "Создать аукцион"}</button>
                  <button type="button" className="mk-ghost" onClick={() => setCreateForm(DEFAULT_CREATE)}>Сбросить форму</button>
                </div>
              </form>
            </Card>
          )}
        </div>
      ) : null}

      {(route.name === "login" || route.name === "register") ? (
        <div className={route.name === "register" ? "mk-auth-page-full" : "mk-page-centered mk-auth-page"}>
          <Card
            title={authMode === "login" ? "Вход" : "Создать аккаунт"}
            subtitle={authMode === "login" ? "Войдите в аккаунт, чтобы делать ставки и управлять аукционами." : "Зарегистрируйте аккаунт участника и начните работу с аукционами."}
          >
            <div className="mk-auth">
              <div className="mk-tabs">
                <button type="button" className={authMode === "login" ? "mk-tab active" : "mk-tab"} onClick={() => { setAuthMode("login"); go({ name: "login" }); }}>Вход</button>
                <button type="button" className={authMode === "register" ? "mk-tab active" : "mk-tab"} onClick={() => { setAuthMode("register"); go({ name: "register" }); }}>Регистрация</button>
              </div>
              {authMode === "login" ? (
                <form className="mk-form" onSubmit={onLogin}>
                  <label className="mk-field-label">Имя пользователя<input value={loginForm.username} onChange={(e) => setLoginForm((f) => ({ ...f, username: e.target.value }))} /></label>
                  <label className="mk-field-label">Пароль<input type="password" value={loginForm.password} onChange={(e) => setLoginForm((f) => ({ ...f, password: e.target.value }))} /></label>
                  <button type="submit" disabled={authLoading}>{authLoading ? "Вход..." : "Войти"}</button>
                </form>
              ) : (
                <form className="mk-form" onSubmit={onRegister}>
                  <div className="mk-form-grid">
                    <label className="mk-field-label">Имя пользователя<input value={registerForm.username} onChange={(e) => setRegisterForm((f) => ({ ...f, username: e.target.value }))} /></label>
                    <label className="mk-field-label">Эл. почта<input type="email" value={registerForm.email} onChange={(e) => setRegisterForm((f) => ({ ...f, email: e.target.value }))} /></label>
                    <label className="mk-field-label">Пароль<input type="password" value={registerForm.password} onChange={(e) => setRegisterForm((f) => ({ ...f, password: e.target.value }))} /></label>
                    <label className="mk-field-label">Роль<select value={registerForm.role} onChange={(e) => setRegisterForm((f) => ({ ...f, role: e.target.value as UserRole }))}><option value="supplier">Поставщик</option><option value="buyer">Покупатель</option></select></label>
                    <label className="mk-field-label">Компания<input value={registerForm.company_name ?? ""} onChange={(e) => setRegisterForm((f) => ({ ...f, company_name: e.target.value }))} /></label>
                    <label className="mk-field-label">ИНН<input value={registerForm.inn ?? ""} inputMode="numeric" pattern="^(?:\\d{10}|\\d{12})$" onChange={(e) => setRegisterForm((f) => ({ ...f, inn: normalizeInnInput(e.target.value) }))} /></label>
                  </div>
                  {registerInnLoading ? <div className="mk-note">Проверяем ИНН в DaData...</div> : null}
                  {registerInnResolved ? <div className="mk-note">Организация найдена: {registerInnResolved}</div> : null}
                  {registerInnError ? <div className="mk-warning">{registerInnError}</div> : null}
                  <button type="submit" disabled={authLoading}>{authLoading ? "Регистрация..." : "Создать аккаунт"}</button>
                </form>
              )}
            </div>
          </Card>
        </div>
      ) : null}

      {route.name === "account" ? (
        <div className="mk-account-page-full">
          <section className="mk-page-content">
            <Card title="Данные аккаунта" subtitle="Основная информация профиля и краткая статистика по вашим аукционам.">
              <div className="mk-account-grid mk-account-grid-profile">
                <div className="mk-kv"><span>Имя пользователя</span><strong>{currentUser?.username ?? "-"}</strong></div>
                <div className="mk-kv"><span>Эл. почта</span><strong>{currentUser?.email ?? "-"}</strong></div>
                <div className="mk-kv"><span>Роль</span><strong>{roleText(currentUser?.profile?.role ?? "-")}</strong></div>
                <div className="mk-kv"><span>Компания</span><strong>{currentUser?.profile?.company_name || "-"}</strong></div>
                <div className="mk-kv"><span>ИНН</span><strong>{currentUser?.profile?.inn || "-"}</strong></div>
                <div className="mk-kv"><span>Рейтинг</span><strong>{currentUser?.profile?.rating ?? "-"}</strong></div>
                <div className="mk-kv"><span>ID пользователя</span><strong>{currentUser?.id ?? userId ?? "-"}</strong></div>
                <div className="mk-kv"><span>Статус сессии</span><strong>{tokens?.access ? "Выполнен вход" : "Гость"}</strong></div>
                <div className="mk-kv"><span>Мои аукционы</span><strong>{myAuctions.length}</strong></div>
                <div className="mk-kv"><span>Участвую в</span><strong>{participatingAuctions.length}</strong></div>
              </div>
              {currentUserLoading && tokens?.access ? <div className="mk-empty small">Загрузка данных аккаунта...</div> : null}
              <div className="mk-inline-actions">
                {!tokens?.access ? <button type="button" onClick={() => go({ name: "login" })}>Войти</button> : null}
                {tokens?.access ? <button type="button" className="mk-ghost" onClick={() => { setStoredTokens(null); setTokens(null); setCurrentUser(null); setOwnedAuctions([]); setParticipatingAuctions([]); setToast({ kind: "ok", text: "Вы вышли из аккаунта." }); }}>Выйти</button> : null}
              </div>
            </Card>
            <Card title="Редактирование аккаунта" subtitle="Изменяйте данные профиля. Эл. почта доступна только для чтения.">
              {!tokens?.access ? <div className="mk-empty">Войдите, чтобы редактировать аккаунт.</div> : null}
              {tokens?.access ? (
                <form className="mk-form" onSubmit={onSaveAccount}>
                  <div className="mk-form-grid">
                    <label className="mk-field-label">Имя пользователя
                      <input value={accountForm.username} onChange={(e) => setAccountForm((f) => ({ ...f, username: e.target.value }))} />
                    </label>
                    <label className="mk-field-label">Эл. почта (только чтение)
                      <input value={accountForm.email} readOnly />
                    </label>
                    <label className="mk-field-label">Роль
                      <select value={accountForm.role} onChange={(e) => setAccountForm((f) => ({ ...f, role: e.target.value as UserRole }))}>
                        <option value="supplier">Поставщик</option>
                        <option value="buyer">Покупатель</option>
                        <option value="admin">Администратор</option>
                      </select>
                    </label>
                    <label className="mk-field-label">Компания
                      <input value={accountForm.company_name} onChange={(e) => setAccountForm((f) => ({ ...f, company_name: e.target.value }))} />
                    </label>
                    <label className="mk-field-label">ИНН
                      <input value={accountForm.inn} inputMode="numeric" pattern="^(?:\\d{10}|\\d{12})$" onChange={(e) => setAccountForm((f) => ({ ...f, inn: normalizeInnInput(e.target.value) }))} />
                    </label>
                    <label className="mk-field-label">Новый пароль (необязательно)
                      <input type="password" value={accountForm.password} onChange={(e) => setAccountForm((f) => ({ ...f, password: e.target.value }))} placeholder="Оставьте пустым, если не хотите менять пароль" />
                    </label>
                  </div>
                  {accountInnLoading ? <div className="mk-note">Проверяем ИНН в DaData...</div> : null}
                  {accountInnResolved ? <div className="mk-note">Организация найдена: {accountInnResolved}</div> : null}
                  {accountInnError ? <div className="mk-warning">{accountInnError}</div> : null}
                  <div className="mk-inline-actions">
                    <button type="submit" disabled={accountSaving}>{accountSaving ? "Сохранение..." : "Сохранить изменения"}</button>
                    <button
                      type="button"
                      className="mk-ghost"
                      onClick={() => {
                        if (!currentUser) return;
                        setAccountForm({
                          username: currentUser.username ?? "",
                          email: currentUser.email ?? "",
                          role: (currentUser.profile?.role as UserRole | undefined) ?? "supplier",
                          company_name: currentUser.profile?.company_name ?? "",
                          inn: currentUser.profile?.inn ?? "",
                          password: "",
                        });
                      }}
                    >
                      Сбросить
                    </button>
                  </div>
                </form>
              ) : null}
            </Card>
            <Card title="Мои аукционы" subtitle="Ваши созданные аукционы. Черновики видны только вам.">
              {!tokens?.access ? <div className="mk-empty">Войдите, чтобы увидеть свои аукционы.</div> : null}
              {ownedAuctionsLoading && tokens?.access ? <div className="mk-empty small">Загрузка аукционов...</div> : null}
              {!ownedAuctionsLoading && tokens?.access && !myAuctions.length ? <div className="mk-empty">У этого аккаунта пока нет созданных аукционов.</div> : null}
              {!!myAuctions.length ? <div className="mk-grid mk-grid-market">{myAuctions.map((a) => <Tile key={a.id} a={a} nowMs={serverNowMs} open={() => openAuction(a.id)} editAction={a.status === "DRAFT" ? { onClick: () => openAuction(a.id), label: "Редактировать" } : undefined} />)}</div> : null}
            </Card>
            <Card title="Аукционы, в которых вы участвуете" subtitle="Список аукционов, где вы уже сделали ставку.">
              {!tokens?.access ? <div className="mk-empty">Войдите, чтобы увидеть аукционы с вашим участием.</div> : null}
              {participatingLoading && tokens?.access ? <div className="mk-empty small">Загрузка аукционов...</div> : null}
              {!participatingLoading && tokens?.access && !participatingAuctions.length ? <div className="mk-empty">Пока нет аукционов с вашим участием.</div> : null}
              {!!participatingAuctions.length ? <div className="mk-grid mk-grid-market">{participatingAuctions.map((a) => <Tile key={a.id} a={a} nowMs={serverNowMs} open={() => openAuction(a.id)} />)}</div> : null}
            </Card>
          </section>
        </div>
      ) : null}

      {toast ? <div className={`mk-toast ${toast.kind}`}>{toast.text}</div> : null}
    </div>
  );
}







