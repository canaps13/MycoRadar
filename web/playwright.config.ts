import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // Bound simultaneous software WebGL contexts on developer machines and CI.
  workers: 2,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: externalBaseURL ?? "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    launchOptions: {
      args: [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
      ],
    },
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: externalBaseURL
    ? undefined
    : [
        {
          command:
            "uv run --locked uvicorn mycoradar.main:app --app-dir api/src --host 127.0.0.1 --port 8000",
          cwd: fileURLToPath(new URL("..", import.meta.url)),
          url: "http://127.0.0.1:8000/health",
          reuseExistingServer: false,
        },
        {
          command: "npm run preview",
          url: "http://127.0.0.1:4173",
          reuseExistingServer: false,
        },
      ],
});
