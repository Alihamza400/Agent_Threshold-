import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard talks to the api-gateway. In development we proxy /v1 to the
// gateway so the SPA never needs CORS; production serves both from the same
// origin (or an explicit origin configured in CORS_ORIGINS).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});