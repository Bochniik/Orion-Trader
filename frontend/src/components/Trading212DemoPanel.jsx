import React, { useEffect, useState } from "react";
import {
  Ban,
  CheckCircle2,
  ClipboardCheck,
  Link2,
  RefreshCw,
  Search,
  ShieldCheck,
  Unplug,
} from "lucide-react";
import {
  cancelTrading212DemoOrder,
  confirmTrading212DemoOrder,
  connectTrading212Demo,
  disconnectTrading212Demo,
  getTrading212DemoOrders,
  getTrading212DemoOverview,
  getTrading212DemoStatus,
  reconcileTrading212DemoOrders,
  reviewTrading212DemoOrder,
  searchTrading212DemoInstruments,
} from "../api/api";


function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value, currency = "EUR") {
  const parsed = number(value);
  if (parsed == null) return "—";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(parsed);
  } catch {
    return `${parsed.toLocaleString()} ${currency}`;
  }
}

function timestamp(item) {
  const value = item?.dateTime || item?.dateCreated || item?.createdAt || item?.paidOn || item?.time;
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function HistoryRows({ title, items = [], currency, type }) {
  return <div className="t212-history-group">
    <div><strong>{title}</strong><span>{items.length} loaded</span></div>
    {items.length === 0 ? <p>No records returned.</p> : <div className="t212-history-list">{items.slice(0, 8).map((item, index) => {
      const ticker = item.ticker || item.instrument?.ticker || item.symbol || item.reference || `Record ${index + 1}`;
      const quantity = item.quantity ?? item.filledQuantity;
      const amount = item.amount ?? item.total ?? item.value ?? item.grossAmount;
      const status = item.status || item.type || item.action || "";
      return <article key={`${type}-${item.id || item.orderId || index}`}>
        <div><strong>{ticker}</strong>{status && <span>{String(status).replaceAll("_", " ")}</span>}</div>
        <p>{quantity != null ? `${quantity} units` : amount != null ? money(amount, currency) : "Details available from Trading 212"}</p>
        {timestamp(item) && <small>{timestamp(item)}</small>}
      </article>;
    })}</div>}
  </div>;
}

const EMPTY_ORDER = {
  ticker: "",
  side: "buy",
  order_type: "limit",
  quantity: "1",
  limit_price: "",
  stop_price: "",
  thesis: "",
  invalidation_price: "",
};

export default function Trading212DemoPanel({
  activeSource = "local",
  onSourceChange,
  onChanged,
}) {
  const [status, setStatus] = useState(null);
  const [overview, setOverview] = useState(null);
  const [credentials, setCredentials] = useState({ api_key: "", api_secret: "" });
  const [query, setQuery] = useState("");
  const [instruments, setInstruments] = useState([]);
  const [draft, setDraft] = useState(EMPTY_ORDER);
  const [review, setReview] = useState(null);
  const [orders, setOrders] = useState([]);
  const [cancelReviewId, setCancelReviewId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function loadTrackedOrders() {
    const result = await getTrading212DemoOrders();
    setOrders(result.orders || []);
    return result;
  }

  async function loadOverview() {
    setBusy(true);
    setMessage("");
    try {
      const next = await getTrading212DemoOverview();
      setOverview(next);
      await loadTrackedOrders();
      const permissionCount = next.permission_limited_sections?.length || 0;
      setMessage(
        permissionCount
          ? `Core account refreshed. ${permissionCount} optional feed${permissionCount === 1 ? " is" : "s are"} unavailable because this API key does not grant that permission.`
          : next.partial_failure
            ? "Core account refreshed with one or more optional feeds temporarily unavailable."
            : "Trading 212 Demo data refreshed.",
      );
      await onChanged?.(status);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    getTrading212DemoStatus()
      .then(async (next) => {
        setStatus(next);
        if (next.connected) {
          const [accountData, orderData] = await Promise.all([
            getTrading212DemoOverview(),
            getTrading212DemoOrders(),
          ]);
          setOverview(accountData);
          setOrders(orderData.orders || []);
        }
      })
      .catch((error) => setMessage(error.message));
  }, []);

  async function connect(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await connectTrading212Demo(credentials.api_key, credentials.api_secret);
      setStatus(result.status);
      setOverview(result.overview);
      setCredentials({ api_key: "", api_secret: "" });
      await loadTrackedOrders();
      setMessage("Trading 212 Demo connected and selected as Orion's active portfolio.");
      await onChanged?.(result.status);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      const next = await disconnectTrading212Demo();
      setStatus(next);
      setOverview(null);
      setReview(null);
      setInstruments([]);
      setMessage("Trading 212 Demo disconnected and credentials removed from server memory.");
      await onChanged?.(next);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function searchInstruments(event) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await searchTrading212DemoInstruments(query.trim());
      setInstruments(result.items || []);
      if (!(result.items || []).length) {
        setMessage("No matching Trading 212 Demo instrument was found.");
      }
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  function selectInstrument(instrument) {
    setDraft((current) => ({ ...current, ticker: instrument.ticker }));
    setQuery(instrument.ticker);
    setInstruments([]);
    setReview(null);
  }

  async function reviewOrder(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const payload = {
        ...draft,
        quantity: Number(draft.quantity),
        limit_price: draft.limit_price === "" ? null : Number(draft.limit_price),
        stop_price: draft.stop_price === "" ? null : Number(draft.stop_price),
        invalidation_price: draft.invalidation_price === "" ? null : Number(draft.invalidation_price),
      };
      const result = await reviewTrading212DemoOrder(payload);
      setReview(result.review);
      await loadTrackedOrders();
      setMessage("Review created. Confirm only after checking every value below.");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmOrder() {
    setBusy(true);
    setMessage("");
    try {
      const result = await confirmTrading212DemoOrder(review.review_id);
      setReview(null);
      setMessage(`Trading 212 Demo order ${result.order.broker_order_id} submitted after manual confirmation.`);
      const reconciled = await reconcileTrading212DemoOrders();
      setOverview(reconciled.overview);
      setOrders(reconciled.orders || []);
      await onChanged?.(status);
    } catch (error) {
      setMessage(error.message);
      await loadTrackedOrders().catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  async function reconcileOrders() {
    setBusy(true);
    setMessage("");
    try {
      const result = await reconcileTrading212DemoOrders();
      setOverview(result.overview);
      setOrders(result.orders || []);
      setMessage(`Reconciliation complete: ${result.updated} order status update${result.updated === 1 ? "" : "s"}, ${result.journal_synced} fill${result.journal_synced === 1 ? "" : "s"} synchronized to Orion.`);
      await onChanged?.(status);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmCancel(reviewId) {
    setBusy(true);
    setMessage("");
    try {
      await cancelTrading212DemoOrder(reviewId);
      setCancelReviewId("");
      setMessage("Trading 212 Demo cancellation requested. Reconcile to confirm the final state.");
      await reconcileOrders();
    } catch (error) {
      setMessage(error.message);
      setBusy(false);
    }
  }

  const account = overview?.account || {};
  const currency = account.currency || "EUR";
  const available = account.cash?.availableToTrade ?? account.cash?.free ?? account.cash?.available;
  const total = account.cash?.total ?? account.totalValue ?? account.equity;
  const invested = account.investments?.currentValue ?? account.cash?.invested ?? account.invested;
  const permissionLimited = overview?.permission_limited_sections || Object.entries(overview?.errors || {})
    .filter(([, detail]) => String(detail).includes("(403)"))
    .map(([name]) => name);
  const otherErrors = Object.entries(overview?.errors || {})
    .filter(([name]) => !permissionLimited.includes(name));
  const isError = /error|unavailable|required|blocked|unknown|failed|disabled/i.test(message);
  const isLimit = draft.order_type === "limit" || draft.order_type === "stop_limit";
  const isStop = draft.order_type === "stop" || draft.order_type === "stop_limit";

  return <section className="card t212-card">
    <div className="section-heading">
      <div>
        <div className="card-title"><Link2 size={20} /> Trading 212 Demo portfolio</div>
        <h2>Portfolio mirror and manually confirmed Demo orders</h2>
      </div>
      <div className="t212-heading-actions">
        <span className="t212-read-only-badge"><ShieldCheck size={14} /> DEMO · MANUAL CONFIRM</span>
        {status?.connected && <div className="source-switch">
          <span>Workspace account</span>
          <button type="button" className={activeSource === "local" ? "primary-btn" : "ghost-btn"} onClick={() => onSourceChange?.("local")}>Local Simulator</button>
          <button type="button" className={activeSource === "trading212_demo" ? "primary-btn" : "ghost-btn"} onClick={() => onSourceChange?.("trading212_demo")}>Trading 212 Demo</button>
        </div>}
      </div>
    </div>
    <p className="broker-safety"><ShieldCheck size={17} /> Fixed Demo endpoint · deterministic limits · review expires before submission · every order and cancellation requires your click · no Live or autonomous Trading 212 route exists.</p>
    {message && <p className={isError ? "warning-text" : "success-text"}>{message}</p>}

    {!status?.connected ? <form className="broker-connect t212-connect" onSubmit={connect}>
      <label>Demo API key<input type="password" autoComplete="off" required value={credentials.api_key} onChange={(event) => setCredentials({ ...credentials, api_key: event.target.value })} /></label>
      <label>Demo API secret<input type="password" autoComplete="off" required value={credentials.api_secret} onChange={(event) => setCredentials({ ...credentials, api_secret: event.target.value })} /></label>
      <button className="primary-btn" type="submit" disabled={busy}>{busy ? "Validating…" : "Connect Trading 212 Demo"}</button>
      <p className="muted-text">Use a Demo API key with account, portfolio, instrument metadata, order and history permissions. Credentials stay only in backend memory and disappear on restart.</p>
    </form> : <>
      <div className="t212-actions">
        <div className="t212-metrics">
          <span>Available<strong>{money(available, currency)}</strong></span>
          <span>Total cash/value<strong>{money(total, currency)}</strong></span>
          <span>Invested<strong>{money(invested, currency)}</strong></span>
          <span>Open positions<strong>{overview?.positions?.length || 0}</strong></span>
        </div>
        <div><button className="ghost-btn" type="button" onClick={loadOverview} disabled={busy}><RefreshCw size={15} className={busy ? "spin" : ""} /> Refresh</button><button className="danger-btn" type="button" onClick={disconnect} disabled={busy}><Unplug size={15} /> Disconnect</button></div>
      </div>

      {!status?.order_submission_enabled && <p className="t212-policy-warning"><Ban size={16} /> Demo order submission is server-disabled. Set <code>TRADING212_DEMO_ORDER_SUBMISSION_ENABLED=true</code> in <code>backend/.env</code> and restart after reviewing the limits.</p>}

      <section className="t212-order-workspace">
        <div className="t212-order-heading">
          <div><h3>Prepare a Demo order</h3><p>Search Trading 212’s instrument directory and select the exact broker ticker.</p></div>
          <button type="button" className="ghost-btn" onClick={reconcileOrders} disabled={busy}><RefreshCw size={15} /> Reconcile orders</button>
        </div>
        <form className="t212-instrument-search" onSubmit={searchInstruments}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search company, ticker or ISIN" />
          <button type="submit" className="ghost-btn" disabled={busy || !query.trim()}><Search size={15} /> Search instruments</button>
        </form>
        {instruments.length > 0 && <div className="t212-instrument-results">{instruments.map((instrument) => <button type="button" key={instrument.ticker} onClick={() => selectInstrument(instrument)}>
          <strong>{instrument.ticker}</strong>
          <span>{instrument.name || instrument.shortName || "Trading 212 instrument"}</span>
          <small>{[instrument.isin, instrument.currencyCode || instrument.currency].filter(Boolean).join(" · ")}</small>
        </button>)}</div>}

        <form className="t212-order-form" onSubmit={reviewOrder}>
          <label>Selected broker ticker<input value={draft.ticker} readOnly placeholder="Choose a search result" required /></label>
          <label>Side<select value={draft.side} onChange={(event) => setDraft({ ...draft, side: event.target.value })}><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
          <label>Order type<select value={draft.order_type} onChange={(event) => setDraft({ ...draft, order_type: event.target.value })}><option value="market">Market</option><option value="limit">Limit</option><option value="stop">Stop</option><option value="stop_limit">Stop limit</option></select></label>
          <label>Quantity<input type="number" min="0.00000001" step="any" required value={draft.quantity} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })} /></label>
          {isLimit && <label>Limit price<input type="number" min="0.0001" step="any" required value={draft.limit_price} onChange={(event) => setDraft({ ...draft, limit_price: event.target.value })} /></label>}
          {isStop && <label>Stop price<input type="number" min="0.0001" step="any" required value={draft.stop_price} onChange={(event) => setDraft({ ...draft, stop_price: event.target.value })} /></label>}
          <label>Thesis<textarea maxLength={4000} value={draft.thesis} onChange={(event) => setDraft({ ...draft, thesis: event.target.value })} placeholder="Why this setup fits your plan" /></label>
          <label>Invalidation price<input type="number" min="0.0001" step="any" value={draft.invalidation_price} onChange={(event) => setDraft({ ...draft, invalidation_price: event.target.value })} placeholder="Optional" /></label>
          <button type="submit" className="primary-btn" disabled={busy || !status?.order_submission_enabled || !draft.ticker}><ClipboardCheck size={16} /> Review Demo order</button>
        </form>

        {review && <div className="t212-order-review">
          <div><strong>{review.side.toUpperCase()} {review.quantity} {review.ticker}</strong><span>{String(review.order_type).replace("_", " ").toUpperCase()}</span></div>
          <p>Estimated value: <strong>{money(review.validation.estimated_notional, review.validation.account.currency)}</strong> · reference {money(review.validation.reference_price, review.validation.instrument.currency)}</p>
          {review.validation.fx && <p>FX validation: 1 {review.validation.fx.to_currency} = {review.validation.fx.rate} {review.validation.fx.from_currency}</p>}
          <ul>{review.validation.gates.map((gate) => <li key={gate.name}><CheckCircle2 size={14} /> <span><strong>{gate.name.replaceAll("_", " ")}</strong> — {gate.message}</span></li>)}</ul>
          <p className="t212-final-warning">This click submits a real order to your Trading 212 <strong>Demo</strong> account. Verify ticker, side, quantity, prices and account before continuing.</p>
          <div><button type="button" className="ghost-btn" onClick={() => setReview(null)} disabled={busy}>Edit</button><button type="button" className="primary-btn" onClick={confirmOrder} disabled={busy}>Confirm Demo order</button></div>
        </div>}
      </section>

      <section className="t212-tracked">
        <div className="t212-order-heading"><div><h3>Orion-tracked Demo orders</h3><p>Broker IDs and statuses are persisted per Orion user; credentials are not.</p></div><span>{orders.length} recorded</span></div>
        {orders.length === 0 ? <p className="muted-text">No Orion-submitted Trading 212 Demo orders yet.</p> : <div className="t212-tracked-list">{orders.slice(0, 12).map((order) => <article key={order.review_id}>
          <div><strong>{order.side.toUpperCase()} {order.quantity} {order.ticker}</strong><span className={`t212-status status-${order.status}`}>{String(order.status).replaceAll("_", " ")}</span></div>
          <p>{String(order.order_type).replaceAll("_", " ")} · {money(order.estimated_notional, order.validation?.account?.currency)} {order.broker_order_id ? `· broker ${order.broker_order_id}` : "· not submitted"}</p>
          {order.status === "reviewed" && <button type="button" className="ghost-btn" onClick={() => setReview(order)}>Open review</button>}
          {["submitted", "pending", "partially_filled"].includes(order.status) && (cancelReviewId === order.review_id
            ? <div className="t212-cancel-confirm"><span>Confirm cancellation request?</span><button type="button" className="ghost-btn" onClick={() => setCancelReviewId("")}>Keep order</button><button type="button" className="danger-btn" onClick={() => confirmCancel(order.review_id)}>Confirm cancel</button></div>
            : <button type="button" className="danger-btn" onClick={() => setCancelReviewId(order.review_id)}>Cancel Demo order</button>)}
        </article>)}</div>}
      </section>

      {overview?.partial_failure && <details className="t212-errors">
        <summary>{otherErrors.length ? "Partial data warning" : "Optional permissions not granted"}</summary>
        <ul>
          {permissionLimited.map((name) => <li key={name}><strong>{name.replaceAll("_", " ")}:</strong> this API key does not grant the optional permission (403). Add it in Trading 212 if you need this feed.</li>)}
          {otherErrors.map(([name, detail]) => <li key={name}><strong>{name.replaceAll("_", " ")}:</strong> {detail}</li>)}
        </ul>
      </details>}
      <div className="t212-data-grid">
        <HistoryRows title="Open positions" items={overview?.positions} currency={currency} type="position" />
        <HistoryRows title="Pending orders" items={overview?.pending_orders} currency={currency} type="pending" />
        <HistoryRows title="Historical orders" items={overview?.historical_orders} currency={currency} type="order" />
        <HistoryRows title="Transactions" items={overview?.transactions} currency={currency} type="transaction" />
        <HistoryRows title="Dividends" items={overview?.dividends} currency={currency} type="dividend" />
      </div>
    </>}
  </section>;
}
