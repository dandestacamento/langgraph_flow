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

/** The app now (Phase E) loads the conversation list and the active
 * thread's history at startup - mock both with empty defaults so the
 * pre-existing tests stay deterministic without a live backend. */
async function mockEmptyThreadRoutes(page: Page): Promise<void> {
  await page.route("**/api/threads", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/threads/*/history", (route) => route.fulfill({ json: [] }));
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
  await mockEmptyThreadRoutes(page);
  await page.route("**/api/chat/stream", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sseBody([
        { event: "status", data: { node: "condense", elapsed_ms: 750 } },
        { event: "status", data: { node: "invoke_routing_pipeline", elapsed_ms: 2300 } },
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
  // Enter-to-send (Shift+Enter is newline) - exercises the composer's
  // keyboard path in a real browser, not just jsdom.
  const composer = page.getByPlaceholder("Type your message…");
  await composer.fill("What does washing machine error E21 mean?");
  await composer.press("Shift+Enter");
  await composer.press("Enter");

  await expect(page.getByText("Drainage problem", { exact: false }).first()).toBeVisible();
  await expect(page.locator("strong", { hasText: "E21" })).toBeVisible();

  await page.getByText("Routing details").click();
  const routingDetailsPanel = page.getByRole("group");
  await expect(routingDetailsPanel.getByText("appliances \u203a washing_machines \u203a chapter_03_faults")).toBeVisible();
  await expect(routingDetailsPanel.getByText(/E21: Drainage problem\. Check the pump filter/)).toBeVisible();
  // The execution timeline (chat-ui-plan3.md §2.2) shows each node's duration.
  await expect(routingDetailsPanel.getByText("invoke_routing_pipeline")).toBeVisible();
  await expect(routingDetailsPanel.getByText("2.3 s")).toBeVisible();

  // Clickable citation (chat-ui-plan3.md §2 item 1): the passage card
  // inside Routing details opens the full passage in a preview panel.
  await routingDetailsPanel.getByRole("button", { name: /chapter_03_faults \(score 0\.79\)/ }).click();
  const preview = page.getByRole("dialog", { name: /chapter_03_faults/ });
  await expect(preview.getByText(/Check the pump filter and drain hose/)).toBeVisible();
  await expect(preview.getByText(/lower = closer match/)).toBeVisible();
  await preview.getByRole("button", { name: "Close" }).click();
  await expect(preview).not.toBeVisible();
});

test("shows an error banner with a working Retry button on a backend failure", async ({ page }) => {
  await mockEmptyThreadRoutes(page);
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

for (const theme of ["light", "dark"] as const) {
  test(`has no serious/critical accessibility violations once a conversation is populated (${theme} mode)`, async ({
    page,
  }) => {
    // The theme is read from localStorage at app startup (useTheme.ts).
    await page.addInitScript((t) => localStorage.setItem("routing-lab3-theme", t), theme);
    await mockEmptyThreadRoutes(page);
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
}

test("lists past conversations in the sidebar, switches between them, and starts a new one", async ({
  page,
}) => {
  await page.route("**/api/threads", (route) =>
    route.fulfill({
      json: [
        {
          thread_id: "thread-fridge",
          title: "Fridge is too warm",
          updated_at: "2026-01-02T00:00:00Z",
        },
        {
          thread_id: "thread-e21",
          title: "What does washing machine error E21 mean?",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    }),
  );
  await page.route("**/api/threads/*/history", (route) => {
    const turns = route.request().url().includes("thread-fridge")
      ? [
          {
            user_message: "Fridge is too warm",
            final_answer: "Check the thermostat.",
            routing_summary: ROUTING_SUMMARY_FIXTURE,
          },
        ]
      : [];
    return route.fulfill({ json: turns });
  });

  await login(page);

  // The sidebar lists both conversations the backend returned.
  const sidebar = page.getByRole("navigation", { name: "Conversations" });
  await expect(sidebar.getByText("Fridge is too warm")).toBeVisible();
  await expect(sidebar.getByText("What does washing machine error E21 mean?")).toBeVisible();

  // Switching restores that conversation's past turns from the backend,
  // the header + browser tab reflect the active conversation, and the
  // restored turn keeps its clickable citations ('the citation is not
  // clickable' regression - restored history used to lose them).
  await sidebar.getByRole("button", { name: /^Fridge is too warm/ }).click();
  await expect(page.getByText("Check the thermostat.")).toBeVisible();
  await expect(page.getByTitle("Fridge is too warm")).toBeVisible();
  await expect(page).toHaveTitle("Fridge is too warm - Appliance Troubleshooting Chat");
  await page.getByText("Routing details").click();
  await page.getByRole("button", { name: /chapter_03_faults \(score 0\.79\)/ }).click();
  await expect(
    page.getByRole("dialog").getByText(/Check the pump filter and drain hose/),
  ).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // "New conversation" starts from a blank window again.
  await sidebar.getByRole("button", { name: "+ New conversation" }).click();
  await expect(page.getByText("Check the thermostat.")).not.toBeVisible();
  await expect(
    page.getByText("Ask a question about appliance troubleshooting to get started."),
  ).toBeVisible();
  await expect(page.getByTitle("New conversation")).toBeVisible();
  await expect(page).toHaveTitle("Appliance Troubleshooting Chat");
});

const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test("attaches an image (picker and clipboard paste) and sends it with the message", async ({
  page,
}) => {
  await mockEmptyThreadRoutes(page);
  let uploadCount = 0;
  await page.route("**/api/threads/*/attachments", (route) => {
    uploadCount += 1;
    return route.fulfill({
      json: {
        attachment_id: `att-e2e-${uploadCount}`,
        filename: "error.png",
        media_type: "image/png",
        size_bytes: TINY_PNG.length,
        extracted_chars: 42,
      },
    });
  });
  await page.route("**/api/threads/*/attachments/*", (route) =>
    route.fulfill({ body: TINY_PNG, contentType: "image/png" }),
  );
  let sentBody: { attachment_ids?: string[] } | null = null;
  await page.route("**/api/chat/stream", async (route) => {
    sentBody = route.request().postDataJSON();
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

  // 1. Picker: attach -> pill -> send; the request carries the id.
  await page.getByLabel("Attach files").setInputFiles({
    name: "error.png",
    mimeType: "image/png",
    buffer: TINY_PNG,
  });
  await expect(page.getByText("error.png")).toBeVisible();
  const composer = page.getByPlaceholder("Type your message…");
  await composer.fill("What does this error mean?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("E21 is a drainage fault.")).toBeVisible();
  expect(sentBody?.attachment_ids).toEqual(["att-e2e-1"]);
  // The sent message shows the image thumbnail (authorized blob fetch).
  await expect(page.locator("img[alt=\"Attachment: error.png\"]")).toBeVisible();

  // 2. Clipboard paste: a pasted screenshot becomes a pending pill too.
  await composer.focus();
  await page.evaluate((pngBase64) => {
    const bytes = Uint8Array.from(atob(pngBase64), (c) => c.charCodeAt(0));
    const data = new DataTransfer();
    data.items.add(new File([bytes], "pasted-image.png", { type: "image/png" }));
    document.activeElement?.dispatchEvent(
      new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }),
    );
  }, TINY_PNG.toString("base64"));
  await expect(page.getByText("pasted-image.png")).toBeVisible();
  expect(uploadCount).toBe(2);

  // 3. The new attachment UI introduces no serious/critical a11y issues.
  const results = await new AxeBuilder({ page }).analyze();
  const seriousOrCritical = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(seriousOrCritical, JSON.stringify(seriousOrCritical, null, 2)).toEqual([]);
});
