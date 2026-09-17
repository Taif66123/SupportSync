import { useState } from "react";
import { api } from "../plugins/api.js";
import { useAppError } from "../stores/appError.js";

/** Create-ticket form (customers only — the API rejects staff creation). */
export function TicketForm({ onCreated }) {
  const [form, setForm] = useState({ title: "", description: "", priority: "medium" });
  const [busy, setBusy] = useState(false);
  const push = useAppError((s) => s.push);
  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const ticket = await api("/tickets", { method: "POST", body: form });
      setForm({ title: "", description: "", priority: "medium" });
      onCreated(ticket);
    } catch (error) {
      push(error.message, error.code);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2 style={{ fontSize: 16, marginTop: 0 }}>New ticket</h2>
      <div className="field">
        <label htmlFor="t-title">Title</label>
        <input id="t-title" value={form.title} onChange={set("title")} placeholder="Brief summary" minLength={5} maxLength={200} required />
      </div>
      <div className="field">
        <label htmlFor="t-desc">What happened?</label>
        <textarea id="t-desc" value={form.description} onChange={set("description")} required />
      </div>
      <div className="field">
        <label htmlFor="t-prio">Priority</label>
        <select id="t-prio" value={form.priority} onChange={set("priority")}>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
      </div>
      <button className="btn" disabled={busy}>Create ticket</button>
    </form>
  );
}
