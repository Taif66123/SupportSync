import { useCallback, useEffect, useState } from "react";
import { api } from "../plugins/api.js";
import { useAuth } from "../stores/auth.js";
import { useAppError } from "../stores/appError.js";
import { fmtDateTime, roleLabel } from "../plugins/format.js";

export default function AdminUsers() {
  const me = useAuth((s) => s.user);
  const push = useAppError((s) => s.push);
  const [page, setPage] = useState(null);
  const [filters, setFilters] = useState({ role: "", is_active: "", q: "" });
  const [newStaff, setNewStaff] = useState({ email: "", password: "", full_name: "", role: "agent" });

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (filters.role) params.set("role", filters.role);
    if (filters.is_active !== "") params.set("is_active", filters.is_active);
    if (filters.q) params.set("q", filters.q);
    setPage(await api(`/users?${params}`));
  }, [filters]);

  useEffect(() => { load().catch((e) => push(e.message, e.code)); }, [load, push]);

  async function run(promiseFactory, after) {
    try {
      await promiseFactory();
      await load();
      after?.();
    } catch (error) {
      push(error.message, error.code);
    }
  }

  const setFilter = (key) => (event) => setFilters((f) => ({ ...f, [key]: event.target.value }));

  return (
    <>
      <h1>User management</h1>

      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault();
          run(() => api("/users", { method: "POST", body: newStaff }), () => setNewStaff({ email: "", password: "", full_name: "", role: "agent" }));
        }}
      >
        <h2 style={{ fontSize: 16, marginTop: 0 }}>Create staff account</h2>
        <div className="filters">
          <div className="field"><label htmlFor="s-name">Full name</label>
            <input id="s-name" value={newStaff.full_name} onChange={(e) => setNewStaff({ ...newStaff, full_name: e.target.value })} required maxLength={200} /></div>
          <div className="field"><label htmlFor="s-email">Email</label>
            <input id="s-email" type="email" value={newStaff.email} onChange={(e) => setNewStaff({ ...newStaff, email: e.target.value })} required /></div>
          <div className="field"><label htmlFor="s-pass">Password</label>
            <input id="s-pass" type="password" value={newStaff.password} onChange={(e) => setNewStaff({ ...newStaff, password: e.target.value })} required minLength={8} /></div>
          <div className="field"><label htmlFor="s-role">Role</label>
            <select id="s-role" value={newStaff.role} onChange={(e) => setNewStaff({ ...newStaff, role: e.target.value })}>
              <option value="agent">Support Agent</option>
              <option value="admin">Admin</option>
            </select></div>
          <div className="field"><label style={{ visibility: "hidden" }}>create</label><button className="btn">Create</button></div>
        </div>
      </form>

      <div className="filters">
        <div className="field">
          <label htmlFor="u-role">Role</label>
          <select id="u-role" value={filters.role} onChange={setFilter("role")}>
            <option value="">Any</option>
            <option value="customer">Customer</option>
            <option value="agent">Support Agent</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="u-active">Status</label>
          <select id="u-active" value={filters.is_active} onChange={setFilter("is_active")}>
            <option value="">Any</option>
            <option value="true">Active</option>
            <option value="false">Deactivated</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="u-q">Search</label>
          <input id="u-q" value={filters.q} onChange={setFilter("q")} placeholder="email or name" maxLength={100} />
        </div>
      </div>

      {page && (
        <table className="list card" style={{ padding: 0 }}>
          <thead>
            <tr><th>User</th><th>Role</th><th>Status</th><th>Created</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {page.items.map((u) => (
              <tr key={u.id}>
                <td>{u.full_name}<br /><small style={{ color: "var(--text-dim)" }}>{u.email}</small></td>
                <td>
                  <select
                    value={u.role}
                    disabled={u.id === me.id}
                    onChange={(e) => run(() => api(`/users/${u.id}/role`, { method: "PATCH", body: { role: e.target.value } }))}
                  >
                    <option value="customer">Customer</option>
                    <option value="agent">Support Agent</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
                <td><span className={`badge ${u.is_active ? "badge-active" : "badge-inactive"}`}>{u.is_active ? "active" : "deactivated"}</span></td>
                <td>{fmtDateTime(u.created_at)}</td>
                <td>
                  {u.id !== me.id && (
                    <button
                      className={`btn btn-small ${u.is_active ? "" : "btn-ghost"}`}
                      onClick={() => run(() => api(`/users/${u.id}/status`, { method: "PATCH", body: { is_active: !u.is_active } }))}
                    >
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
