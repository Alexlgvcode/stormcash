import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, /v1 is proxied to the FastAPI server, so the dashboard and the API
// share an origin. For a deployed build, set VITE_API_BASE to the server URL.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/v1": { target: process.env.STORMCASH_API ?? "http://localhost:8000", changeOrigin: true } },
  },
});
