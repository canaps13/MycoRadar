import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Local same-origin proxy; no permissive CORS or browser-side credentials needed.
const proxy = {
  "/api": {
    target: "http://127.0.0.1:8000",
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
