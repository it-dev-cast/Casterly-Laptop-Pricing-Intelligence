import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8010 and is proxied, so the UI and API share an origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: { "/api": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8010", changeOrigin: false } },
  },
});
