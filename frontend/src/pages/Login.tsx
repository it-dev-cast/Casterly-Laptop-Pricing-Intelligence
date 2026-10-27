import { useState, type FormEvent } from "react";
import { useApp } from "../context";

export default function Login() {
  const { login } = useApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="loginwrap">
      <div className="loginart">
        <div className="brandmark" style={{ padding: 0 }}>
          <div className="logo"><img src="/brand/casterly-mark.png" alt="" /></div>
          <div>
            <div className="t1">CASTERLY</div>
            <div className="t2">Laptop Pricing Intelligence</div>
          </div>
        </div>
        <div>
          <h1>Know what a refurbished laptop is worth before you buy it.</h1>
          <p>
            Selling ranges, target and maximum safe buying prices for every line in a lot, each one traceable to the
            comparables, adjustments and assumptions behind it.
          </p>
        </div>
        <div className="small" style={{ color: "#a9a3d3" }}>
          Prices come from a deterministic engine. Language models only explain results and suggest extracted fields
          for review.
        </div>
      </div>
      <div className="loginform">
        <form onSubmit={submit}>
          <img className="loginlogo" src="/brand/casterly-logo.png" alt="Casterly" />
          <h2>Sign in</h2>
          <label className="field">
            Email
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label className="field">
            Password
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error && <div className="banner bad">{error}</div>}
          <button className="btn primary" disabled={busy} type="submit" style={{ justifyContent: "center" }}>
            {busy ? <span className="spin" /> : "Sign in"}
          </button>
          <div className="muted small">Accounts are created by an administrator.</div>
        </form>
      </div>
    </div>
  );
}
