import { create } from "zustand";

/**
 * Live notifications: one EventSource per logged-in session, a small toast
 * queue, and a per-view callback hook (the ticket detail view subscribes to
 * hear about its own ticket). `?token=` auth — EventSource cannot set headers.
 */
export const useNotifications = create((set, get) => ({
  source: null,
  toasts: [],
  _viewCallback: null,

  connect(accessToken) {
    get().disconnect();
    const url = `${import.meta.env.VITE_API_URL || ""}/api/v1/notifications/stream?token=${encodeURIComponent(accessToken)}`;
    const source = new EventSource(url);
    const deliver = (event) => {
      const data = JSON.parse(event.data);
      set((state) => ({
        toasts: [...state.toasts.slice(-4), { id: Date.now() + Math.random(), ...data }],
      }));
      get()._viewCallback?.(data);
    };
    for (const type of ["ticket.created", "ticket.updated", "message.created"]) {
      source.addEventListener(type, deliver);
    }
    set({ source });
  },

  disconnect() {
    get().source?.close();
    set({ source: null, toasts: [], _viewCallback: null });
  },

  onTicketEvent(callback) {
    set({ _viewCallback: callback });
  },

  dismiss(id) {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
}));
