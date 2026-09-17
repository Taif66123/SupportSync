import { useCallback, useEffect, useRef, useState } from "react";
import { api, wsUrl } from "../plugins/api.js";
import { fmtTime } from "../plugins/format.js";
import { useAuth } from "../stores/auth.js";
import { useAppError } from "../stores/appError.js";

const TYPING_THROTTLE_MS = 3000;

/**
 * Per-ticket live chat. One WebSocket per mounted panel (single-process rooms —
 * a documented M3 constraint). Frames are the typed backend protocol:
 * out: message.send / typing.start / read.up-to; in: connect.ack / message.new /
 * typing.start / read.receipt / error.
 */
export function ChatPanel({ ticket }) {
  const me = useAuth((s) => s.user);
  const accessToken = useAuth((s) => s.accessToken);
  const push = useAppError((s) => s.push);

  const [messages, setMessages] = useState([]);
  const [canSend, setCanSend] = useState(false);
  const [connected, setConnected] = useState(false);
  const [draft, setDraft] = useState("");
  const [typingUserId, setTypingUserId] = useState(null);
  // userId -> last message id they have read (drives the ✓✓ marks).
  const [receipts, setReceipts] = useState({});

  const wsRef = useRef(null);
  const typingSentAt = useRef(0);
  const typingTimer = useRef(null);
  const logRef = useRef(null);
  const stopped = useRef(false);

  const send = useCallback((frame) => wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send(JSON.stringify(frame)), []);

  // History + read markers once per ticket.
  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setReceipts({});
    (async () => {
      try {
        const [page, states] = await Promise.all([
          api(`/tickets/${ticket.id}/messages?limit=100`),
          api(`/tickets/${ticket.id}/messages/read-states`),
        ]);
        if (cancelled) return;
        setMessages(page.items);
        setReceipts(Object.fromEntries(states.map((s) => [s.user_id, s.last_read_message_id])));
      } catch (error) {
        push(error.message, error.code);
      }
    })();
    return () => { cancelled = true; };
  }, [ticket.id, push]);

  // The socket: connect with ?token= (browsers cannot set WS headers).
  useEffect(() => {
    stopped.current = false;
    let retry;

    const connect = () => {
      if (stopped.current) return;
      const ws = new WebSocket(wsUrl(`/tickets/${ticket.id}/ws?token=${encodeURIComponent(accessToken)}`));
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (!stopped.current) retry = setTimeout(connect, 3000); // rooms are best-effort live
      };
      ws.onmessage = (event) => {
        const frame = JSON.parse(event.data);
        if (frame.type === "connect.ack") {
          setCanSend(frame.can_send);
        } else if (frame.type === "message.new") {
          const message = frame.message;
          setMessages((prev) => (prev.some((m) => m.id === message.id) ? prev : [...prev, message]));
          // Reading up to the newest visible message — but never past my own words.
          if (document.visibilityState === "visible" && message.sender_id !== me.id) {
            send({ type: "read.up-to", message_id: message.id });
          }
        } else if (frame.type === "typing.start") {
          setTypingUserId(frame.user_id);
          clearTimeout(typingTimer.current);
          typingTimer.current = setTimeout(() => setTypingUserId(null), 3000);
        } else if (frame.type === "read.receipt") {
          setReceipts((prev) => ({ ...prev, [frame.user_id]: Math.max(prev[frame.user_id] ?? 0, frame.message_id) }));
        } else if (frame.type === "error") {
          push(frame.message, frame.code);
        }
      };
    };

    connect();
    return () => {
      stopped.current = true;
      clearTimeout(retry);
      clearTimeout(typingTimer.current);
      wsRef.current?.close();
    };
  }, [ticket.id, accessToken, me.id, send, push]);

  // Keep the log scrolled to the newest message.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages, typingUserId]);

  const onDraftChange = (event) => {
    setDraft(event.target.value);
    if (canSend && Date.now() - typingSentAt.current > TYPING_THROTTLE_MS) {
      typingSentAt.current = Date.now();
      send({ type: "typing.start" });
    }
  };

  function submitMessage(event) {
    event.preventDefault();
    const body = draft.trim();
    if (!body || !canSend) return;
    setDraft("");
    send({ type: "message.send", body });
  }

  // ✓✓ on my messages: any OTHER participant has read past this message.
  const otherReceipts = Object.entries(receipts).filter(([id]) => Number(id) !== me.id);
  const othersTyping = typingUserId !== null && typingUserId !== me.id;

  return (
    <div className="card">
      <div className="btn-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>Conversation</h2>
        <span className="chat-hint" style={{ marginTop: 0 }}>{connected ? "live" : "connecting…"}</span>
      </div>
      <div className="chat">
        <div className="chat-log" ref={logRef}>
          {messages.length === 0 && <div className="empty">No messages yet.</div>}
          {messages.map((m) => {
            const mine = m.sender_id === me.id;
            const seen = mine && otherReceipts.some(([, lastRead]) => lastRead >= m.id);
            return (
              <div key={m.id} className={`chat-msg ${mine ? "mine" : ""}`}>
                <div>{m.body}</div>
                <div className="meta">
                  {mine ? "you" : `user #${m.sender_id}`} · {fmtTime(m.created_at)}
                  {mine && <span className="read">{seen ? "✓✓" : "✓"}</span>}
                </div>
              </div>
            );
          })}
          {othersTyping && <div className="chat-hint">user #{typingUserId} is typing…</div>}
        </div>
        <form className="chat-input" onSubmit={submitMessage}>
          <input
            value={draft}
            onChange={onDraftChange}
            placeholder={canSend ? "Type a message…" : "Read-only (closed, or observer)"}
            disabled={!connected || !canSend}
            maxLength={4000}
          />
          <button className="btn" disabled={!canSend || !draft.trim()}>Send</button>
        </form>
      </div>
    </div>
  );
}
