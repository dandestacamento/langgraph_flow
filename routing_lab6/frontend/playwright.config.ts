import { defineConfig } from "@playwright/test";

/**
 * E2E smoke tests mock the backend at the network boundary (see
 * e2e/chat.spec.ts) rather than requiring a live FastAPI + OpenAI-backed
 * server - this keeps the suite deterministic and free to run in CI.
 * The actual pipeline's correctness is already covered exhaustively by
 * routing_lab6/tests' 228-row/10-level ground truth; this suite's job is
 * to verify the *frontend's own* behavior (SSE parsing, rendering,
 * error/retry handling) against controlled fixture responses.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
