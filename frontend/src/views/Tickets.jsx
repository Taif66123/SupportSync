import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../plugins/api.js";
import { useAuth } from "../stores/auth.js";
import { useNotifications } from "../stores/notifications.js";
import { TicketForm } from "../components/TicketForm.jsx";
import { fmtDateTime, statusLabel } from "../plugins/format.js";

export default function Tickets() {
  const user = useAuth((s) => s.user);
  const onTicketEvent = useNotifications((s) => s.onTicketEvent);
  const [page, setPage] = useState(null);
  const [filters, setFilters] = useState({ status: "", priority: "", mine: false });

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.priority) params.set("priority", filters.priority);
    if (filters.mine) params.set("mine", "true");
    setPage(await api(`/tickets?${params}`));
  }, [filters]);

  useEffect(() => { load().catch(console.error); }, [load]);

  // Live list: new tickets and status changes re-render the queue without a refresh.
  useEffect(() => {
    onTicketEvent((event) => {
      if (event.type === "ticket.created" || event.type === "ticket.updated") load().catch(() => {});
    });
    return () => onTicketEvent(null);
  }, [load, onTicketEvent]);

  const set = (key) => (event) =>
    setFilters((f) => ({ ...f, [key]: key === "mine" ? event.target.checked : event.target.value }));

  return (
    <>
      <h1>Tickets</h1>
      <div className="filters">
        <div className="field">
          <label htmlFor="f-status">Status</label>
          <select id="f-status" value={filters.status} onChange={set("status")}>
            <option value="">Any</option>
            {["open", "in_progress", "resolved", "closed"].map((s) => (
              <option key={s} value={s}>{statusLabel(s)}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-prio">Priority</label>
          <select id="f-prio" value={filters.priority} onChange={set("priority")}>
            <option value="">Any</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>
        {user.role !== "customer" && (
          <div className="field">
            <label htmlFor="f-mine" style={{ visibility: "hidden" }}>mine</label>
            <label><input id="f-mine" type="checkbox" checked={filters.mine} onChange={set("mine")} /> Assigned to me</label>
          </div>
        )}
      </div>

      {page && (
        <table className="list card" style={{ padding: 0 }}>
          <thead>
            <tr><th>#</th><th>Title</th><th>Status</th><th>Priority</th><th>Created</th></tr>
          </thead>
          <tbody>
            {page.items.map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td><Link to={`/tickets/${t.id}`}>{t.title}</Link></td>
                <td><span className={`badge badge-${t.status}`}>{statusLabel(t.status)}</span></td>
                <td><span className={`badge badge-${t.priority}`}>{t.priority}</span></td>
                <td>{fmtDateTime(t.created_at)}</td>
              </tr>
            ))}
            {page.items.length === 0 && (
              <tr><td colSpan={5} className="empty">No tickets match.</td></tr>
            )}
          </tbody>
        </table>
      )}
      <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
        {page ? `${page.total} total · showing ${page.items.length} (offset ${page.offset})` : "Loading…"}
      </p>

      {user.role === "customer" && <TicketForm onCreated={(t) => { load().catch(() => {}); }} />}
    </>
  );
}
