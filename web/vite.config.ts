/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API calls go to the local gateway (Kong), exactly as in production.
const gateway = process.env.GATEWAY_URL ?? "http://localhost";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": { target: gateway, changeOrigin: true } } },
  test: { environment: "jsdom", globals: false, setupFiles: ["./src/test/setup.ts"] },
});
