import { useAuth } from "../stores/auth.js";

const BASE = (import.meta.env.VITE_API_URL || "") + "/api/v1";

/**
 * The one fetch wrapper. Same shape as the backend's error contract:
 * every non-OK response becomes an ApiError carrying {code, message}.
 * A 401 with a refresh token triggers exactly one transparent refresh
 * attempt before the error propagates (401 during refresh -> logged out).
 */
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function apiUrl(path) {
  return `${BASE}${path}`;
}

/** WS endpoint from an API path — same-origin uses the Vite ws proxy. */
export function wsUrl(path) {
  if (!import.meta.env.VITE_API_URL) {
    const { protocol, host } = window.location;
    return `${protocol === "https:" ? "wss" : "ws"}://${host}${BASE}${path}`;
  }
  return `${import.meta.env.VITE_API_URL.replace(/^http/, "ws")}${BASE}${path}`;
}

export async function api(path, { method = "GET", body, token, retry = true } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const access = token ?? useAuth.getState().accessToken;
  if (access) headers["Authorization"] = `Bearer ${access}`;

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 && retry && useAuth.getState().refreshToken) {
    const refreshed = await useAuth.getState().refresh();
    if (refreshed) return api(path, { method, body, retry: false });
  }
  if (!response.ok) {
    let code = "http_error", message = `request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (payload?.error) ({ code, message } = payload.error);
    } catch { /* non-JSON body — keep defaults */ }
    throw new ApiError(response.status, code, message);
  }
  if (response.status === 204) return null;
  return response.json();
}
