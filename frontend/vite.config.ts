/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.RIDE_PULSE_BACKEND ?? "http://127.0.0.1:8000";

// Dev: Vite serves the app on :5173 and proxies the API and WebSockets to Django.
// Build: assets land in dist/ and Django serves them under /static/app/.
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/app/" : "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/admin": backend,
      "/static": backend,
      "/media": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router"],
          map: ["leaflet", "react-leaflet"],
          charts: ["recharts"],
          "google-maps": ["@vis.gl/react-google-maps"],
        },
      },
    },
  },
  test: {
    environment: "node",
  },
}));
