import { useState } from "react";
import { BookOpen, Wallet } from "lucide-react";
import { updateTradeJournal } from "../api/api";

function currency(value, currencyCode = "USD") {
  try {
    return Number(value || 0).toLocaleString(undefined, {
      style: "currency",
      currency: currencyCode,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  } catch {
    return `${Number(value || 0).toLocaleString()} ${currencyCode}`;
  }
}

function positionPrice(position, accountCurrency, isTrading212) {
  if (!isTrading212 || position.price_currency) {
    return currency(position.average_price, position.price_currency || accountCurrency);
  }
  return Number(position.average_price || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function JournalEditor({ trade, onSaved }) {
  const journal = trade.journal || {};
  const [open, setOpen] = useState(false);
  const [thesis, setThesis] = useState(journal.thesis || "");
  const [invalidationPrice, setInvalidationPrice] = useState(journal.invalidation_price ?? "");
  const [notes, setNotes] = useState(journal.post_trade_notes || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save(event) {
    event.preventDefault();
    try {
      setSaving(true);
      setError("");
      await updateTradeJournal(trade.id, {
        thesis,
        invalidation_price: invalidationPrice === "" ? null : Number(invalidationPrice),
        post_trade_notes: notes,
      });
      setOpen(false);
      await onSaved?.();
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="trade-journal">
      <button type="button" className="ghost-btn" onClick={() => setOpen((value) => !value)}>
        <BookOpen size={13} /> {journal.thesis || journal.post_trade_notes ? "Edit journal" : "Add thesis"}
      </button>
      {open && (
        <form className="trade-journal-form" onSubmit={save}>
          <textarea value={thesis} onChange={(event) => setThesis(event.target.value)} maxLength={4000} placeholder="Why did you take this trade?" />
          <input type="number" min="0.01" step="0.01" value={invalidationPrice} onChange={(event) => setInvalidationPrice(event.target.value)} placeholder="Invalidation price" />
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={4000} placeholder="Post-trade notes and lessons" />
          {error && <span className="error-text">{error}</span>}
          <button type="submit" className="primary-btn" disabled={saving}>{saving ? "Saving..." : "Save journal"}</button>
        </form>
      )}
    </div>
  );
}

export default function PortfolioPanel({ portfolio, onJournalSaved }) {
  const positions = portfolio?.positions || {};
  const trades = portfolio?.trades || [];
  const stats = portfolio?.journal_statistics || {};
  const currencyCode = portfolio?.currency || "USD";
  const isLocal = portfolio?.source === "local";
  const isAlpaca = portfolio?.source === "alpaca";
  const isTrading212 = portfolio?.source === "trading212_demo";

  return (
    <div className="card">
      <div className="card-title"><Wallet size={20} /> {portfolio?.source_label || "Portfolio"}</div>
      <div className="portfolio-metrics">
        <div><span>Total value</span><strong>{currency(portfolio?.total_value, currencyCode)}</strong></div>
        <div><span>{isAlpaca ? "Day P&L" : "Total P&L"}</span><strong>{currency(portfolio?.total_pnl, currencyCode)}</strong></div>
        <div><span>{isAlpaca ? "Buying power" : isTrading212 ? "Available cash" : "Realized"}</span><strong>{currency(isAlpaca ? portfolio?.buying_power : isTrading212 ? portfolio?.cash : portfolio?.realized_pnl, currencyCode)}</strong></div>
        <div><span>Unrealized</span><strong>{currency(portfolio?.unrealized_pnl, currencyCode)}</strong></div>
      </div>

      {isLocal && <><h3>Journal performance</h3>
      <div className="portfolio-metrics journal-metrics">
        <div><span>Expectancy</span><strong>{stats.expectancy == null ? "—" : currency(stats.expectancy, currencyCode)}</strong></div>
        <div><span>Payoff ratio</span><strong>{stats.payoff_ratio ?? "—"}</strong></div>
        <div><span>Win rate</span><strong>{stats.win_rate == null ? "—" : `${stats.win_rate}%`}</strong></div>
        <div><span>Current streak</span><strong>{stats.current_streak?.length ? `${stats.current_streak.length} ${stats.current_streak.type}` : "—"}</strong></div>
      </div></>}

      <h3>Positions</h3>
      {Object.keys(positions).length === 0 ? <p>No open positions yet.</p> : (
        <div className="table-scroll"><table><thead><tr><th>Ticker</th><th>Qty</th><th>Avg</th><th>Value</th><th>Allocation</th><th>P&amp;L</th></tr></thead>
          <tbody>{Object.entries(positions).map(([symbol, position]) => (
            <tr key={symbol}><td>{position.ticker || symbol}{position.broker_symbol && position.broker_symbol !== position.ticker ? <small className="position-broker-symbol">{position.broker_symbol}{position.valuation_estimated ? " · value allocated from broker total" : ""}</small> : null}</td><td>{position.quantity}</td><td>{positionPrice(position, currencyCode, isTrading212)}</td><td>{currency(position.market_value, currencyCode)}</td><td>{position.allocation_percent ?? 0}%</td><td className={(position.unrealized_pnl || 0) >= 0 ? "green" : "red"}>{currency(position.unrealized_pnl, currencyCode)}</td></tr>
          ))}</tbody></table></div>
      )}

      {isAlpaca ? <p className="muted-text">Positions are synchronized from Alpaca Paper for review. This interface does not submit orders.</p> : isTrading212 ? <><p className="muted-text">Positions are synchronized from Trading 212 Demo for review. This interface does not prepare or submit orders.</p><h3>Existing Demo trade history</h3>
      {trades.length === 0 ? <p>No Orion-submitted Demo fills have been reconciled yet.</p> : (
        <div className="trade-list">{trades.slice().reverse().slice(0, 8).map((trade) => (
          <div className="trade trade-with-journal" key={trade.id}>
            <div className="trade-summary"><span className={trade.type === "BUY" ? "green" : "red"}>{trade.type}</span><span>{trade.ticker}</span><span>{trade.quantity} units</span><span>{currency(trade.price, trade.price_currency || currencyCode)}</span><span>{trade.broker_order_id}</span></div>
            {trade.journal?.thesis && <p className="muted-text"><strong>Thesis:</strong> {trade.journal.thesis}</p>}
          </div>
        ))}</div>
      )}</> : <><h3>Recent trades</h3>
      {trades.length === 0 ? <p>No trades yet.</p> : (
        <div className="trade-list">{trades.slice().reverse().slice(0, 8).map((trade) => (
          <div className="trade trade-with-journal" key={trade.id}>
            <div className="trade-summary"><span className={trade.type === "BUY" ? "green" : "red"}>{trade.type}</span><span>{trade.ticker}</span><span>{trade.quantity} {trade.quantity === 1 ? "share" : "shares"}</span><span>{currency(trade.price, currencyCode)}</span>{trade.realized_pnl != null && <span className={trade.realized_pnl >= 0 ? "green" : "red"}>{currency(trade.realized_pnl, currencyCode)}</span>}</div>
            {trade.journal?.thesis && <p className="muted-text"><strong>Thesis:</strong> {trade.journal.thesis}</p>}
            <JournalEditor trade={trade} onSaved={onJournalSaved} />
          </div>
        ))}</div>
      )}
      {portfolio?.trades_truncated && <p className="muted-text">Showing the latest 200 of {portfolio.trade_count} trades.</p>}</>}
    </div>
  );
}
