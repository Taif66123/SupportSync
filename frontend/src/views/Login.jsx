import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../stores/auth.js";
import { useAppError } from "../stores/appError.js";

/** Login for existing accounts; customers can self-register. */
export default function Login() {
  const login = useAuth((s) => s.login);
  const register = useAuth((s) => s.register);
  const push = useAppError((s) => s.push);
  const navigate = useNavigate();

  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", full_name: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(form.email, form.password);
      else await register({ email: form.email, password: form.password, full_name: form.full_name });
      navigate("/tickets");
    } catch (err) {
      setError(err.message);
      push(err.message, err.code);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 420, margin: "48px auto" }}>
      <form className="card" onSubmit={submit}>
        <h1>{mode === "login" ? "Log in" : "Create a customer account"}</h1>
        {mode === "register" && (
          <div className="field">
            <label htmlFor="l-name">Full name</label>
            <input id="l-name" value={form.full_name} onChange={set("full_name")} required maxLength={200} />
          </div>
        )}
        <div className="field">
          <label htmlFor="l-email">Email</label>
          <input id="l-email" type="email" value={form.email} onChange={set("email")} required autoComplete="username" />
        </div>
        <div className="field">
          <label htmlFor="l-pass">Password</label>
          <input id="l-pass" type="password" value={form.password} onChange={set("password")} required
            minLength={mode === "register" ? 8 : 1} autoComplete={mode === "register" ? "new-password" : "current-password"} />
        </div>
        {error && <p className="error-text">{error}</p>}
        <button className="btn" disabled={busy} style={{ width: "100%" }}>
          {busy ? "…" : mode === "login" ? "Log in" : "Register"}
        </button>
        <p style={{ fontSize: 13, marginBottom: 0 }}>
          {mode === "login" ? "New customer? " : "Already have an account? "}
          <a href="#" onClick={(e) => { e.preventDefault(); setMode(mode === "login" ? "register" : "login"); setError(null); }}>
            {mode === "login" ? "Create an account" : "Log in"}
          </a>
        </p>
      </form>
    </div>
  );
}
