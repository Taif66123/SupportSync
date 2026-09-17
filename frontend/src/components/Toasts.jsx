import { useAppError } from "../stores/appError.js";
import { useNotifications } from "../stores/notifications.js";
import { statusLabel } from "../plugins/format.js";

function Stack({ items, onDismiss, render }) {
  if (items.length === 0) return null;
  return (
    <div className="toast-stack">
      {items.map((item) => (
        <div key={item.id} className={`toast ${item.kind === "error" ? "toast-error" : ""}`} onClick={() => onDismiss(item.id)}>
          {render(item)}
        </div>
      ))}
    </div>
  );
}

/** Both toast surfaces: global errors and live notifications. */
export function Toasts() {
  const errors = useAppError((s) => s.errors);
  const dismissError = useAppError((s) => s.dismiss);
  const toasts = useNotifications((s) => s.toasts);
  const dismissToast = useNotifications((s) => s.dismiss);

  return (
    <>
      <Stack
        items={errors}
        onDismiss={dismissError}
        render={(e) => (
          <>
            <small>{e.code}</small>
            {e.message}
          </>
        )}
      />
      <Stack
        items={toasts}
        onDismiss={dismissToast}
        render={(t) => (
          <>
            <small>{t.type}</small>
            {t.type === "message.created"
              ? `New message on "${t.payload.ticket_title ?? `ticket #${t.payload.ticket_id}`}"`
              : t.type === "ticket.created"
                ? `New ticket: "${t.payload.title}"`
                : `Ticket #${t.payload.ticket_id} → ${statusLabel(t.payload.status ?? "")}`}
          </>
        )}
      />
    </>
  );
}
