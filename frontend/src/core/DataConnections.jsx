import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { connectAlpaca, disconnectAlpaca, connectTrading212Demo, disconnectTrading212Demo, getWorkspace, setWorkspaceSource } from "../api/api";
import useAsyncTask from "./useAsyncTask";

export default function DataConnections({ onClose, onChanged, user, onLogout }) {
  const dialog = useRef(null);
  const workspace = useAsyncTask();
  const [provider, setProvider] = useState("alpaca");
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { dialog.current?.showModal(); workspace.run(() => getWorkspace()); }, []);
  async function mutate(action) {
    setBusy(true); setError("");
    try { await action(); setKey(""); setSecret(""); await workspace.run(() => getWorkspace()); await onChanged(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  const data = workspace.data;
  const connected = provider === "alpaca" ? data?.alpaca?.connected : data?.trading212_demo?.connected;
  return <dialog ref={dialog} className="core-dialog core-shell" onCancel={onClose} aria-labelledby="data-title">
    <div className="core-dialog-heading"><h2 id="data-title">Data & account</h2><button className="core-icon-button" type="button" aria-label="Close data settings" onClick={onClose}><X size={20} /></button></div>
    <p>Analysis assistant only. These connections provide research data and account snapshots; there are no order controls here.</p>
    {workspace.error && <p role="alert">{workspace.error}</p>}
    <label htmlFor="data-provider">Connection</label><select id="data-provider" value={provider} onChange={event => { setProvider(event.target.value); setKey(""); setSecret(""); setError(""); }}>
      <option value="alpaca">Alpaca Paper · market research data</option><option value="trading212_demo">Trading 212 Demo · portfolio data</option>
    </select>
    <p className="core-muted">{provider === "alpaca" ? "Current scanner inputs use IEX snapshots. Coverage is limited; this is not consolidated depth or guaranteed real-time pricing." : "Demo portfolio only. Trading 212 does not supply the Live Edge model feed."}</p>
    {workspace.busy ? <p role="status">Checking connection…</p> : connected ? <div className="core-connected"><span>Connected</span><button type="button" className="core-button secondary" disabled={busy} onClick={() => mutate(provider === "alpaca" ? disconnectAlpaca : disconnectTrading212Demo)}>Disconnect</button></div> : <form onSubmit={event => { event.preventDefault(); mutate(() => provider === "alpaca" ? connectAlpaca(key, secret) : connectTrading212Demo(key, secret)); }}>
      <label htmlFor="data-key">{provider === "alpaca" ? "Paper API key" : "Demo API key"}</label><input id="data-key" type="password" value={key} autoComplete="off" required onChange={event => setKey(event.target.value)} />
      <label htmlFor="data-secret">Secret key</label><input id="data-secret" type="password" value={secret} autoComplete="off" required onChange={event => setSecret(event.target.value)} />
      <button className="core-button" type="submit" disabled={busy}>{busy ? "Connecting…" : "Connect data"}</button>
    </form>}
    {error && <p className="core-warning" role="alert">{error}</p>}
    <p className="core-muted">Credentials remain in backend memory, disappear on restart and are not stored in your browser.</p>
    {data && <><label htmlFor="portfolio-source">Portfolio displayed in My Stocks</label><select id="portfolio-source" value={data.active_source} disabled={busy} onChange={event => mutate(() => setWorkspaceSource(event.target.value))}>
      <option value="local">Local simulated portfolio</option>{data.alpaca?.connected && <option value="alpaca">Alpaca Paper</option>}{data.trading212_demo?.connected && <option value="trading212_demo">Trading 212 Demo</option>}
    </select></>}
    <div className="core-account"><span>{user?.email}</span><button type="button" className="core-text-button" onClick={onLogout}>Sign out</button></div>
  </dialog>;
}
