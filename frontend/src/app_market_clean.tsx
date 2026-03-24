import { FormEvent, ReactNode, startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  closeAuction,
  createAuction,
  fetchCurrentUser,
  fetchActiveAuctions,
  fetchAuction,
  fetchAuctionBids,
  fetchAuctionWinner,
  fetchMyAuctions,
  fetchAuctions,
  fetchMyParticipatingAuctions,
  fetchServerTime,
  getStoredApiBase,
  getStoredTokens,
  loginUser,
  normalizeAuction,
  registerUser,
  setStoredTokens,
  submitBid,
  updateAuction,
  updateCurrentUser,
} from "./api";
import type {
  Auction,
  AuctionCreatePayload,
  Bid,
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
  status: "DRAFT" | "PUBLISHED";
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
  status: "DRAFT",
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
  const [authLoading, setAuthLoading] = useState(false);
  const [createForm, setCreateForm] = useState<CreateForm>(DEFAULT_CREATE);
  const [createLoading, setCreateLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [currentUserLoading, setCurrentUserLoading] = useState(false);
  const [ownedAuctions, setOwnedAuctions] = useState<Auction[]>([]);
  const [ownedAuctionsLoading, setOwnedAuctionsLoading] = useState(false);
  const [participatingAuctions, setParticipatingAuctions] = useState<Auction[]>([]);
  const [participatingLoading, setParticipatingLoading] = useState(false);
  const [accountForm, setAccountForm] = useState<AccountForm>(DEFAULT_ACCOUNT_FORM);
  const [accountSaving, setAccountSaving] = useState(false);
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
    } catch (e) { setToast({ kind: "error", text: `Не удалось загрузить аукционы: ${(e as Error).message}` }); }
    finally { setLoadingAuctions(false); }
  }
  async function loadAuction(id: number, silent = false) {
    if (!silent) setLoadingAuction(true);
    try { setAuction(normalizeAuction(await fetchAuction(id, apiBase, tokens?.access ?? undefined))); }
    catch (e) { setAuction(null); setToast({ kind: "error", text: `Не удалось загрузить аукцион: ${(e as Error).message}` }); }
    finally { if (!silent) setLoadingAuction(false); }
  }
  async function loadBids(id: number) {
    if (!tokens?.access) { setBids([]); setBidsMsg("Войдите, чтобы посмотреть историю ставок."); return; }
    setLoadingBids(true); setBidsMsg("");
    try { const data = await fetchAuctionBids(id, tokens.access, apiBase); setBids(data); if (!data.length) setBidsMsg("Ставок пока нет."); }
    catch (e) { setBids([]); setBidsMsg((e as Error).message); }
    finally { setLoadingBids(false); }
  }
  async function loadWinner(id: number) {
    if (!tokens?.access) { setWinner(null); setWinnerMsg("Войдите, чтобы проверить победителя."); return; }
    setLoadingWinner(true); setWinnerMsg("");
    try { setWinner(await fetchAuctionWinner(id, tokens.access, apiBase)); }
    catch (e) { setWinner(null); setWinnerMsg((e as Error).message); }
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
  }, [auction?.id, auction?.title, auction?.description, auction?.start_price, auction?.start_date, auction?.end_date, auction?.specific?.min_bid_decrement]);
  useEffect(() => { if (!selectedId) return; startTransition(() => { void loadAuction(selectedId); }); }, [selectedId, apiBase]);
  useEffect(() => { if (route.name === "auction" && detailTab === "bids" && selectedId) void loadBids(selectedId); }, [route, detailTab, selectedId, apiBase, tokens?.access]);

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
    catch (err) { setToast({ kind: "error", text: `Ошибка входа: ${(err as Error).message}` }); }
    finally { setAuthLoading(false); }
  }
  async function onRegister(e: FormEvent) {
    e.preventDefault(); setAuthLoading(true);
    try { const res = await registerUser({ ...registerForm, role: registerForm.role === "admin" ? "supplier" : registerForm.role }, apiBase); setLoginForm((f) => ({ ...f, username: res.username })); setToast({ kind: "ok", text: `Аккаунт создан: ${res.username}.` }); go({ name: "login" }); }
    catch (err) { setToast({ kind: "error", text: `Ошибка регистрации: ${(err as Error).message}` }); }
    finally { setAuthLoading(false); }
  }
  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!tokens?.access) { setToast({ kind: "error", text: "Сначала войдите в аккаунт, чтобы создать аукцион." }); return; }
    const payload: AuctionCreatePayload = {
      title: createForm.title,
      description: createForm.description,
      start_price: Number(createForm.start_price),
      start_date: new Date(createForm.start_date_local).toISOString(),
      end_date: new Date(createForm.end_date_local).toISOString(),
      status: createForm.status,
      auction_type: "reverseenglishauction",
      min_bid_decrement: Number(createForm.min_bid_decrement),
    };
    setCreateLoading(true);
    try { const created = normalizeAuction(await createAuction(payload, tokens.access, apiBase)); setCreateForm(DEFAULT_CREATE); setToast({ kind: "ok", text: `Аукцион создан.` }); await refreshAuctions(); await loadOwnedAuctions(tokens.access); openAuction(created.id); }
    catch (err) { setToast({ kind: "error", text: `Ошибка создания: ${(err as Error).message}` }); }
    finally { setCreateLoading(false); }
  }
  async function onBid(e: FormEvent) {
    e.preventDefault(); if (!auction) return;
    if (!tokens?.access) { setToast({ kind: "error", text: "Сначала войдите в аккаунт, чтобы сделать ставку." }); go({ name: "login" }); return; }
    setBidLoading(true);
    try { const result = await submitBid(auction.id, tokens.access, bidForm, apiBase); window.location.href = result.redirect_url; }
    catch (err) { setToast({ kind: "error", text: `Ошибка ставки: ${(err as Error).message}` }); }
    finally { setBidLoading(false); }
  }
  async function onSaveAccount(e: FormEvent) {
    e.preventDefault();
    if (!tokens?.access) {
      setToast({ kind: "error", text: "Сначала войдите в аккаунт." });
      return;
    }
    const payload: CurrentUserUpdatePayload = {
      username: accountForm.username.trim(),
      role: accountForm.role,
      company_name: accountForm.company_name,
      inn: accountForm.inn,
    };
    if (accountForm.password.trim()) payload.password = accountForm.password;

    setAccountSaving(true);
    try {
      const updated = await updateCurrentUser(payload, tokens.access, apiBase);
      setCurrentUser(updated);
      setAccountForm((f) => ({ ...f, password: "" }));
      setToast({ kind: "ok", text: "Данные аккаунта обновлены." });
    } catch (err) {
      setToast({ kind: "error", text: `Ошибка обновления: ${(err as Error).message}` });
    } finally {
      setAccountSaving(false);
    }
  }
  async function onUpdateDraft(nextStatus: "DRAFT" | "PUBLISHED") {
    if (!auction || !tokens?.access) {
      setToast({ kind: "error", text: "Сначала войдите в аккаунт." });
      return;
    }
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
          status: nextStatus,
        },
        tokens.access,
        apiBase,
      );
      const normalized = normalizeAuction(updated);
      setAuction(normalized);
      await refreshAuctions();
      await loadOwnedAuctions(tokens.access);
      setToast({ kind: "ok", text: nextStatus === "PUBLISHED" ? "Аукцион опубликован." : "Черновик сохранен." });
    } catch (err) {
      setToast({ kind: "error", text: `Ошибка обновления: ${(err as Error).message}` });
    } finally {
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
      setToast({ kind: "error", text: `Ошибка закрытия: ${(err as Error).message}` });
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

      {route.name === "auction" ? <div className="mk-detail-layout"><section className="mk-detail-main"><Card title={auction?.title || "Аукцион"} subtitle={auction ? `Активный аукцион` : "Выберите аукцион из списка."} action={auction ? <Status s={auction.status} /> : undefined}>{loadingAuction ? <div className="mk-empty">Загрузка аукциона...</div> : null}{!loadingAuction && !auction ? <div className="mk-empty">Аукцион не найден.</div> : null}{auction ? <div className="mk-detail"><div className="mk-product-hero"><div className="mk-product-gallery" aria-hidden="true"><div className="mk-product-gallery-main">{(auction.title || "А")[0].toUpperCase()}</div><div className="mk-product-gallery-row"><span /><span /><span /></div></div><div className="mk-product-summary"><p className="mk-product-copy">{auction.description || "Описание отсутствует."}</p><div className="mk-detail-stats"><div><small>Текущая цена</small><strong>{money(auction.current_price ?? auction.start_price)}</strong></div><div><small>Начальная цена</small><strong>{money(auction.start_price)}</strong></div><div><small>До окончания</small><strong>{timeLeft(auction.end_date, serverNowMs)}</strong></div><div><small>Мин. шаг снижения</small><strong>{auction.specific?.min_bid_decrement ?? "-"}</strong></div></div><div className="mk-meta-list"><span>Начало: {dateText(auction.start_date)}</span><span>Окончание: {dateText(auction.end_date)}</span><span>Продавец</span></div></div></div><div className="mk-tabs compact mk-segmented"><button type="button" className={detailTab === "overview" ? "mk-tab active" : "mk-tab"} onClick={() => setDetailTab("overview")}>Обзор</button><button type="button" className={detailTab === "bids" ? "mk-tab active" : "mk-tab"} onClick={() => { setDetailTab("bids"); void loadBids(auction.id); }}>Ставки</button></div>{detailTab === "overview" ? <div className="mk-lots"><div className="mk-subhead"><span>Лоты</span><small>{auction.lots?.length ?? 0}</small></div>{(auction.lots ?? []).map((lot) => <div key={`${lot.id}-${lot.code}`} className="mk-lot-row"><div><strong>{lot.name}</strong><span>{lot.code || "Позиция"}</span></div><div><strong>{lot.quantity}</strong><span>{lot.unit}</span></div></div>)}{!auction.lots?.length ? <div className="mk-empty small">Лоты пока не добавлены.</div> : null}</div> : <div className="mk-bids">{bidsMsg ? <div className="mk-warning">{bidsMsg}</div> : null}{loadingBids ? <div className="mk-empty small">Загрузка ставок...</div> : null}{!loadingBids && bids.map((b) => <div key={b.id} className="mk-bid-row"><div><strong>{money(b.bid)}</strong><span>Поставщик</span></div><p>{b.comment || "Без комментария"}</p></div>)}{!loadingBids && !bids.length && !bidsMsg ? <div className="mk-empty small">Ставок пока нет.</div> : null}</div>}</div> : null}</Card></section><aside className="mk-detail-side"><Card title={isOwnerDraft ? "Редактирование черновика" : "Сделать ставку"} subtitle={isOwnerDraft ? "Редактировать можно только черновики. Когда все готово, опубликуйте аукцион." : "Отправьте новую ставку для этого аукциона."}>{!auction ? <div className="mk-empty small">Сначала выберите аукцион.</div> : isOwnerDraft ? <form className="mk-form" onSubmit={(e) => { e.preventDefault(); void onUpdateDraft("DRAFT"); }}><div className="mk-form-grid"><label className="mk-field-label">Название<input value={draftEditForm.title} onChange={(e) => setDraftEditForm((f) => ({ ...f, title: e.target.value }))} /></label><label className="mk-field-label">Начальная цена<input type="number" step="0.01" value={draftEditForm.start_price} onChange={(e) => setDraftEditForm((f) => ({ ...f, start_price: e.target.value }))} /></label><label className="mk-field-label">Время начала<input type="datetime-local" value={draftEditForm.start_date_local} onChange={(e) => setDraftEditForm((f) => ({ ...f, start_date_local: e.target.value }))} /></label><label className="mk-field-label">Время окончания<input type="datetime-local" value={draftEditForm.end_date_local} onChange={(e) => setDraftEditForm((f) => ({ ...f, end_date_local: e.target.value }))} /></label><label className="mk-field-label">Мин. шаг снижения<input type="number" step="0.01" value={draftEditForm.min_bid_decrement} onChange={(e) => setDraftEditForm((f) => ({ ...f, min_bid_decrement: e.target.value }))} /></label></div><label className="mk-field-label">Описание<textarea rows={4} value={draftEditForm.description} onChange={(e) => setDraftEditForm((f) => ({ ...f, description: e.target.value }))} /></label><div className="mk-inline-actions"><button type="submit" disabled={draftEditLoading}>{draftEditLoading ? "Сохранение..." : "Сохранить черновик"}</button><button type="button" className="mk-ghost" disabled={draftEditLoading} onClick={() => void onUpdateDraft("PUBLISHED")}>{draftEditLoading ? "Подождите..." : "Опубликовать"}</button>{canOwnerCloseAuction ? <button type="button" className="mk-ghost" disabled={draftEditLoading} onClick={() => void onCloseAuction()}>{draftEditLoading ? "Подождите..." : "Закрыть аукцион"}</button> : null}</div></form> : isAuctionOwner ? <div className="mk-empty small">Этот аукцион уже опубликован. Владелец не может редактировать его или делать ставки.</div> : !tokens?.access ? <div className="mk-empty small">Войдите как поставщик, чтобы делать ставки.</div> : !canBidByRole ? <div className="mk-empty small">Ставки в этом аукционе могут делать только поставщики.</div> : auction.status !== "ACTIVE" ? <div className="mk-empty small">Прием ставок начнется, когда аукцион станет активным.</div> : <form className="mk-form" onSubmit={onBid}><label className="mk-field-label">Цена ставки (чем ниже, тем лучше)<input type="number" step="0.01" min="0" value={bidForm.bid_amount} onChange={(e) => setBidForm((f) => ({ ...f, bid_amount: e.target.value }))} placeholder="Введите более низкую цену" /></label><label className="mk-field-label">Комментарий (необязательно)<input value={bidForm.comment} onChange={(e) => setBidForm((f) => ({ ...f, comment: e.target.value }))} placeholder="Срок поставки, примечания" /></label><div className="mk-inline-actions"><button type="submit" disabled={bidLoading}>{bidLoading ? "Отправка..." : "Отправить ставку"}</button><button type="button" className="mk-ghost" onClick={() => void loadBids(auction.id)}>Обновить ставки</button><button type="button" className="mk-ghost" onClick={() => void loadWinner(auction.id)}>Проверить победителя</button></div>{(loadingWinner || winner || winnerMsg) ? <div className="mk-winner-box">{loadingWinner ? <span>Проверка победителя...</span> : null}{winner ? <span>Текущий победитель: {money(winner.bid)}</span> : null}{!winner && winnerMsg ? <span>{winnerMsg}</span> : null}</div> : null}</form>}</Card>{isAuctionOwner && !isOwnerDraft && canOwnerCloseAuction ? <Card title="Действия владельца" subtitle="Управление статусом аукциона."><div className="mk-inline-actions"><button type="button" className="mk-ghost" onClick={() => void onCloseAuction()}>Закрыть аукцион</button></div></Card> : null}<Card title="Другие аукционы" subtitle="Откройте другой активный или недавний аукцион."><div className="mk-list-rows">{(activeAuctions.length ? activeAuctions : allAuctions).slice(0, 6).map((a) => <button key={a.id} type="button" className="mk-row-link" onClick={() => openAuction(a.id)}><div><strong>{a.title}</strong><span>{statusText(a.status)}</span></div><div><strong>{money(a.current_price ?? a.start_price)}</strong><span>{timeLeft(a.end_date, serverNowMs)}</span></div></button>)}{!(activeAuctions.length || allAuctions.length) ? <div className="mk-empty small">Нет доступных аукционов.</div> : null}</div></Card></aside></div> : null}

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
                  <label className="mk-field-label">Режим сохранения<select value={createForm.status} onChange={(e) => setCreateForm((f) => ({ ...f, status: e.target.value as "DRAFT" | "PUBLISHED" }))}><option value="DRAFT">Черновик</option><option value="PUBLISHED">Опубликовать</option></select></label>
                  <label className="mk-field-label">Тип аукциона<input value="Реверсный аукцион" readOnly /></label>
                </div>
                <label className="mk-field-label">Описание<textarea rows={4} value={createForm.description} onChange={(e) => setCreateForm((f) => ({ ...f, description: e.target.value }))} placeholder="Условия поставки, требования к участникам, комментарии" /></label>
                <div className="mk-inline-actions">
                  <button type="submit" disabled={createLoading}>{createLoading ? "Сохранение..." : (createForm.status === "DRAFT" ? "Сохранить черновик" : "Создать аукцион")}</button>
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
                    <label className="mk-field-label">ИНН<input value={registerForm.inn ?? ""} onChange={(e) => setRegisterForm((f) => ({ ...f, inn: e.target.value }))} /></label>
                  </div>
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
                      <input value={accountForm.inn} onChange={(e) => setAccountForm((f) => ({ ...f, inn: e.target.value }))} />
                    </label>
                    <label className="mk-field-label">Новый пароль (необязательно)
                      <input type="password" value={accountForm.password} onChange={(e) => setAccountForm((f) => ({ ...f, password: e.target.value }))} placeholder="Оставьте пустым, если не хотите менять пароль" />
                    </label>
                  </div>
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







