import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies same-origin /api to the backend (no CORS in dev by default).
// Set VITE_API_URL=http://127.0.0.1:8000 to talk cross-origin instead — that is
// the mode that exercises the backend's CORS_ORIGINS whitelist end to end.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, ws: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
