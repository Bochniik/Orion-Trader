import { useState } from "react";
import { LogIn, ShieldCheck, Sparkles, UserPlus } from "lucide-react";
import { loginAccount, registerAccount } from "../api/api";
import OrionMark from "./OrionMark";

export default function AuthPanel({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function submit(event) {
    event.preventDefault();
    try { setLoading(true); setError(""); const data = mode === "login" ? await loginAccount(email, password) : await registerAccount(email, password); onAuthenticated(data); }
    catch (submitError) { setError(submitError.message); } finally { setLoading(false); }
  }
  return <main className="auth-screen">
    <div className="auth-aurora auth-aurora-one" aria-hidden="true" />
    <div className="auth-aurora auth-aurora-two" aria-hidden="true" />
    <section className="auth-experience">
      <div className="auth-story">
        <OrionMark size={92} className="auth-orion-mark" />
        <span className="auth-kicker"><Sparkles size={14} /> AI-assisted market research</span>
        <h1>Trade with a process,<br /><em>not an impulse.</em></h1>
        <p>See what deserves attention, analyze one stock, and keep your saved stocks close. Three focused workflows, with the evidence behind every conclusion.</p>
        <div className="auth-trust-row"><span><ShieldCheck size={14} /> No trade execution</span><span><ShieldCheck size={14} /> Private user data</span><span><ShieldCheck size={14} /> Evidence before action</span></div>
      </div>
      <section className="card auth-card">
        <div className="auth-card-heading"><span>{mode === "login" ? "WELCOME BACK" : "CREATE WORKSPACE"}</span><h2>{mode === "login" ? "Enter OrionTrader" : "Start your research cockpit"}</h2><p>Your private assistant workspace awaits.</p></div>
        <form onSubmit={submit}><label>Email<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>Password<input type="password" minLength={12} autoComplete={mode === "login" ? "current-password" : "new-password"} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <p className="error-text">{error}</p>}<button className="primary-btn" type="submit" disabled={loading}>{mode === "login" ? <LogIn size={16} /> : <UserPlus size={16} />}{loading ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}</button></form>
        <button className="ghost-btn" type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "Create the first account" : "I already have an account"}</button>
      </section>
    </section>
  </main>;
}
