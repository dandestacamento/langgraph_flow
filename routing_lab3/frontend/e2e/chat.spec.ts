import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

/**
 * Mocks the backend's `/api/chat/stream` SSE contract (per
 * app/api/main.py and src/api/client.ts) directly at the network
 * boundary - keeps this suite deterministic and free of any live
 * LLM/backend dependency, per playwright.config.ts's module docstring.
 * Authentication is NOT mocked - the app now requires a real login via
 * Keycloak (instructions/learnings/chat-ui-plan1.md section 2.3/Phase
 * D), so `login` below drives the actual OIDC redirect against the
 * demo realm in routing_lab3/infra/keycloak - that realm must be
 * running (`docker compose up -d` from routing_lab3/, or the
 * `keycloak` service container in CI) for this suite to pass.
 */
function sseBody(events: Array<{ event: string; data: unknown }>): string {
  return events.map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

async function login(page: Page, username = "demo", password = "demo-password"): Promise<void> {
  await page.goto("/");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.waitForURL("**/localhost:5173/**");
}

const ROUTING_SUMMARY_FIXTURE = {
  topics: ["appliances"],
  subtopics: { appliances: "washing_machines" },
  chapters: { appliances: "chapter_03_faults" },
  passages: {
    appliances: [
      {
        chapter_id: "chapter_03_faults",
        document_id: "doc1",
        subtopic: "washing_machines",
        score: 0.79,
        text: "E21: Drainage problem. Check the pump filter and drain hose for blockages.",
      },
    ],
  },
  tool_results: {},
  is_multi_hop: false,
  hop_results: [],
  recovery_attempts: {},
};

test("sends a message, shows streaming status, then renders the Markdown answer with routing details", async ({
  page,
}) => {
  await page.route("**/api/chat/stream", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sseBody([
        { event: "status", data: { node: "condense" } },
        { event: "status", data: { node: "rag_retriever" } },
        {
          event: "answer",
          data: {
            final_answer:
              "**E21**: Drainage problem. Check the pump filter and drain hose for blockages.",
            routing_summary: ROUTING_SUMMARY_FIXTURE,
          },
        },
      ]),
    });
  });

  await login(page);
  await page.getByPlaceholder("Type your message…").fill("What does washing machine error E21 mean?");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Drainage problem", { exact: false }).first()).toBeVisible();
  await expect(page.locator("strong", { hasText: "E21" })).toBeVisible();

  await page.getByText("Routing details").click();
  const routingDetailsPanel = page.getByRole("group");
  await expect(routingDetailsPanel.getByText("appliances \u203a washing_machines \u203a chapter_03_faults")).toBeVisible();
  await expect(routingDetailsPanel.getByText(/E21: Drainage problem\. Check the pump filter/)).toBeVisible();
});

test("shows an error banner with a working Retry button on a backend failure", async ({ page }) => {
  let callCount = 0;
  await page.route("**/api/chat/stream", async (route) => {
    callCount += 1;
    if (callCount === 1) {
      await route.fulfill({ status: 502, body: "Bad Gateway" });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          {
            event: "answer",
            data: { final_answer: "Recovered answer.", routing_summary: ROUTING_SUMMARY_FIXTURE },
          },
        ]),
      });
    }
  });

  await login(page);
  await page.getByPlaceholder("Type your message…").fill("Trigger a failure");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText(/Chat stream request failed: 502/)).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("Recovered answer.")).toBeVisible();
  expect(callCount).toBe(2);
});

test("has no serious/critical accessibility violations once a conversation is populated", async ({ page }) => {
  await page.route("**/api/chat/stream", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sseBody([
        {
          event: "answer",
          data: { final_answer: "E21 is a drainage fault.", routing_summary: ROUTING_SUMMARY_FIXTURE },
        },
      ]),
    });
  });

  await login(page);
  await page.getByPlaceholder("Type your message…").fill("What does washing machine error E21 mean?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("E21 is a drainage fault.")).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  const seriousOrCritical = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(seriousOrCritical, JSON.stringify(seriousOrCritical, null, 2)).toEqual([]);
});
