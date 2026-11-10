import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { Agent } from "node:http";

// Local same-origin proxy; no permissive CORS or browser-side credentials needed.
const proxy = {
  "/api": {
    target: process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000",
    agent: new Agent({ keepAlive: true }),
    // Avoid premature upstream closure of larger JSON responses on local Windows.
    headers: { connection: "keep-alive" },
    rewrite: (path: string) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    clearMocks: true,
  },
});
