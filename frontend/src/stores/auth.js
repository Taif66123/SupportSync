import { create } from "zustand";
import { ApiError, api } from "../plugins/api.js";

const STORAGE_KEY = "supportsync.auth";

function loadSaved() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) ?? {};
  } catch {
    return {};
  }
}

/**
 * Token pair + the logged-in user. Persisted to localStorage so a reload
 * keeps the session; `refresh()` rotates the refresh token (the backend
 * rejects reuse — a failed rotation is a logout).
 */
export const useAuth = create((set, get) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  ...loadSaved(),

  _persist({ accessToken, refreshToken, user }) {
    set({ accessToken, refreshToken, user });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ accessToken, refreshToken, user }));
  },

  async login(email, password) {
    const tokens = await api("/auth/login", { method: "POST", body: { email, password } });
    const user = await api("/users/me", { token: tokens.access_token });
    get()._persist({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, user });
  },

  async register(payload) {
    const tokens = await api("/auth/register", { method: "POST", body: payload });
    const user = await api("/users/me", { token: tokens.access_token });
    get()._persist({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, user });
  },

  async refresh() {
    const { refreshToken } = get();
    if (!refreshToken) return false;
    try {
      const tokens = await api("/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshToken },
      });
      let user = get().user;
      if (!user) user = await api("/users/me", { token: tokens.access_token });
      get()._persist({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, user });
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        get().logout(); // rotated token was reused/expired — the session is dead
      }
      return false;
    }
  },

  logout() {
    const { refreshToken } = get();
    if (refreshToken) {
      api("/auth/logout", { method: "POST", body: { refresh_token: refreshToken }, retry: false }).catch(() => {});
    }
    set({ accessToken: null, refreshToken: null, user: null });
    localStorage.removeItem(STORAGE_KEY);
  },
}));
