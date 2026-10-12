import { useState } from "react";
import {
  BarChart3,
  Eye,
  EyeOff,
  LockKeyhole,
  LogIn,
  Mail,
  ShieldCheck,
  Sparkles,
  UserPlus,
} from "lucide-react";
import { loginAccount, registerAccount } from "../api/api";
import OrionMark from "./OrionMark";

export default function AuthPanel({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    try {
      setLoading(true);
      setError("");
      const data = mode === "login"
        ? await loginAccount(email, password)
        : await registerAccount(email, password);
      onAuthenticated(data);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setLoading(false);
    }
  }

  function switchMode() {
    setMode((currentMode) => currentMode === "login" ? "register" : "login");
    setError("");
  }

  return (
    <main className="auth-screen">
      <div className="auth-starfield" aria-hidden="true" />
      <div className="auth-planet" aria-hidden="true" />
      <div className="auth-orbit auth-orbit-one" aria-hidden="true" />
      <div className="auth-orbit auth-orbit-two" aria-hidden="true" />
      <div className="auth-market-ghost" aria-hidden="true">
        <i /><i /><i /><i /><i /><i /><i /><i /><i />
      </div>
      <div className="auth-aurora auth-aurora-one" aria-hidden="true" />
      <div className="auth-aurora auth-aurora-two" aria-hidden="true" />

      <section className="auth-experience">
        <div className="auth-story">
          <div className="auth-brand-lockup">
            <OrionMark size={92} className="auth-orion-mark" />
          </div>

          <span className="auth-kicker">
            <Sparkles size={15} />
            AI-assisted market research
            <b aria-hidden="true" />
          </span>

          <h1>
            Trade with a<br />
            process,<br />
            <em>not an impulse.</em>
          </h1>

          <p>
            See what deserves attention, analyze one stock, and keep your saved
            stocks close. Three focused workflows, with the evidence behind every
            conclusion.
          </p>

          <div className="auth-trust-row" aria-label="OrionTrader principles">
            <span><ShieldCheck size={15} /> No trade execution</span>
            <span><LockKeyhole size={15} /> Private user data</span>
            <span><BarChart3 size={15} /> Evidence before action</span>
          </div>
        </div>

        <section className="card auth-card" aria-labelledby="auth-title">
          <div className="auth-card-glow" aria-hidden="true" />
          <div className="auth-card-heading">
            <span>{mode === "login" ? "WELCOME BACK" : "CREATE WORKSPACE"}</span>
            <h2 id="auth-title">
              {mode === "login" ? "Enter OrionTrader" : "Start your research cockpit"}
            </h2>
            <p>
              {mode === "login"
                ? "Your private assistant workspace awaits."
                : "Create your private OrionTrader workspace."}
            </p>
          </div>

          <form onSubmit={submit}>
            <label>
              <span>Email</span>
              <span className="auth-input-shell">
                <Mail size={18} aria-hidden="true" />
                <input
                  type="email"
                  autoComplete="email"
                  required
                  placeholder="you@example.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </span>
            </label>

            <label>
              <span>Password</span>
              <span className="auth-input-shell">
                <LockKeyhole size={18} aria-hidden="true" />
                <input
                  type={showPassword ? "text" : "password"}
                  minLength={12}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                  placeholder="Minimum 12 characters"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
                <button
                  className="auth-password-toggle"
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </span>
            </label>

            {error && <p className="error-text" role="alert">{error}</p>}

            <button className="primary-btn" type="submit" disabled={loading}>
              {mode === "login" ? <LogIn size={18} /> : <UserPlus size={18} />}
              {loading ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <div className="auth-divider"><span>or</span></div>

          <button className="ghost-btn" type="button" onClick={switchMode}>
            <UserPlus size={17} />
            {mode === "login" ? "Create the first account" : "I already have an account"}
          </button>

          <p className="auth-card-footnote">
            Private research workspace · No brokerage execution
          </p>
        </section>
      </section>
    </main>
  );
}
