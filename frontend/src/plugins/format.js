export function roleLabel(role) {
  return { customer: "Customer", agent: "Support Agent", admin: "Admin" }[role] ?? role;
}

export function statusLabel(status) {
  return { open: "Open", in_progress: "In progress", resolved: "Resolved", closed: "Closed" }[status] ?? status;
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
