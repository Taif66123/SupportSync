import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../plugins/api.js";
import { useAuth } from "../stores/auth.js";
import { useNotifications } from "../stores/notifications.js";
import { ChatPanel } from "../components/ChatPanel.jsx";
import { fmtDateTime, statusLabel } from "../plugins/format.js";

/** Which lifecycle actions this role may offer right now (server re-checks —
 * this only hides buttons the policy would reject anyway). */
function availableActions(ticket, user) {
  if (ticket.status === "closed") return [];
  const actions = [];
  if (user.role === "agent" && ticket.status === "open" && ticket.agent_id == null) {
    actions.push({ key: "claim", label: "Claim" });
  }
  if (user.role === "agent" && ticket.status === "in_progress" && ticket.agent_id === user.id) actions.push({ key: "resolve", label: "Resolve" });
  if (user.role === "agent" && ticket.status === "resolved" && ticket.agent_id === user.id) actions.push({ key: "reopen", label: "Reopen" });
  if (ticket.customer_id === user.id || user.role === "agent" || user.role === "admin") {
    actions.push({ key: "close", label: "Close" });
  }
  return actions;
}

export default function TicketDetail() {
  const { id } = useParams();
  const me = useAuth((s) => s.user);
  const accessToken = useAuth((s) => s.accessToken);
  const onTicketEvent = useNotifications((s) => s.onTicketEvent);
  const [ticket, setTicket] = useState(null);
  const [error, setError] = useState(null);
  const [agents, setAgents] = useState(null);
  const [priority, setPriority] = useState("");

  const load = useCallback(async () => {
    try {
      setTicket(await api(`/tickets/${id}`));
    } catch (err) {
      setError(err.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Live header: a status change arriving over SSE re-renders without refresh.
  useEffect(() => {
    onTicketEvent((event) => {
      if (event.type === "ticket.updated" && event.payload.ticket_id === Number(id)) load();
    });
    return () => onTicketEvent(null);
  }, [id, load, onTicketEvent]);

  useEffect(() => { if (ticket) setPriority(ticket.priority); }, [ticket]);

  async function act(action) {
    try {
      if (action === "claim") await api(`/tickets/${id}/claim`, { method: "POST" });
      else if (action === "resolve") await api(`/tickets/${id}/resolve`, { method: "POST" });
      else if (action === "reopen") await api(`/tickets/${id}/reopen`, { method: "POST" });
      else if (action === "close") await api(`/tickets/${id}/close`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function assignTo(agentId) {
    if (!agentId) return;
    try {
      await api(`/tickets/${id}/assign`, { method: "POST", body: { agent_id: Number(agentId) } });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function changePriority(event) {
    try {
      await api(`/tickets/${id}/priority`, { method: "PATCH", body: { priority: event.target.value } });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (error) return <><h1>Ticket</h1><p className="error-text">{error}</p></>;
  if (!ticket) return <p className="empty">Loading…</p>;

  const canManagePriority = me.role === "agent" || me.role === "admin";
  if (canManagePriority && me.role === "admin" && !agents) {
    api("/users?role=agent&limit=100").then((p) => setAgents(p.items)).catch(() => setAgents([]));
  }
  const actions = availableActions(ticket, me);

  return (
    <>
      <div className="btn-row" style={{ justifyContent: "space-between" }}>
        <h1>#{ticket.id} — {ticket.title}</h1>
        <span className={`badge badge-${ticket.status}`}>{statusLabel(ticket.status)}</span>
      </div>
      <div className="card">
        <p style={{ whiteSpace: "pre-wrap", margin: "0 0 10px" }}>{ticket.description}</p>
        <div className="btn-row" style={{ color: "var(--text-dim)", fontSize: 13 }}>
          <span className={`badge badge-${ticket.priority}`}>{ticket.priority}</span>
          <span>opened {fmtDateTime(ticket.created_at)}</span>
          {ticket.closed_at && <span>closed {fmtDateTime(ticket.closed_at)}</span>}
        </div>
        {canManagePriority && ticket.status !== "closed" && (
          <div className="field" style={{ marginTop: 12, maxWidth: 220 }}>
            <label htmlFor="t-prio-edit">Priority</label>
            <select id="t-prio-edit" value={priority} onChange={changePriority}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </div>
        )}
        {actions.length > 0 && (
          <div className="btn-row" style={{ marginTop: 12 }}>
            {actions.map((a) => (
              <button key={a.key} className="btn btn-small" onClick={() => act(a.key)}>{a.label}</button>
            ))}
          </div>
        )}
        {me.role === "admin" && ticket.status === "open" && ticket.agent_id == null && (
          <div className="btn-row" style={{ marginTop: 12 }}>
            <label htmlFor="t-assign" style={{ fontSize: 13, color: "var(--text-dim)" }}>Assign agent:</label>
            <select id="t-assign" defaultValue="" onChange={(e) => { assignTo(e.target.value); e.target.value = ""; }}>
              <option value="" disabled>choose…</option>
              {(agents ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.full_name}</option>
              ))}
            </select>
          </div>
        )}
        {error && <p className="error-text">{error}</p>}
      </div>
      <ChatPanel ticket={ticket} accessToken={accessToken} />
    </>
  );
}
