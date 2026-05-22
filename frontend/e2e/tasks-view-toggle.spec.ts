import { expect, test } from "@playwright/test";

import {
  API_BASE,
  PROJECT_ID,
  WORKSPACE_ID,
  makeTask,
  setupTaskBoardMocks,
} from "./fixtures/task-test-helpers";

/**
 * Covers two things wired together:
 *   1. A project-scoped custom status (slug "design_review") surfaces as a
 *      kanban column on /sprints/{projectId}/board (Part B wiring).
 *   2. The Board ↔ Table layout toggle persists per-scope, replacing the
 *      previously orphaned Settings2 button.
 *
 * Mocked end-to-end so failures point at the wiring, not at backend timing.
 */
test.describe("Board page: project-scoped statuses + view toggle", () => {
  test.beforeEach(async ({ page }) => {
    await setupTaskBoardMocks(page);

    // Project-scoped status set: 5 default-ish + 1 custom slug.
    await page.route(
      `${API_BASE}/workspaces/${WORKSPACE_ID}/task-statuses**`,
      (route) => {
        const url = route.request().url();
        const projectScoped = url.includes(`project_id=${PROJECT_ID}`);
        const baseRows = [
          { slug: "backlog", name: "Backlog", category: "backlog", color: "#9CA3AF", position: 0 },
          { slug: "todo", name: "To Do", category: "todo", color: "#3B82F6", position: 1 },
          { slug: "in_progress", name: "In Progress", category: "in_progress", color: "#F59E0B", position: 2 },
          { slug: "design_review", name: "Design Review", category: "in_review", color: "#EC4899", position: 3 },
          { slug: "done", name: "Done", category: "done", color: "#10B981", position: 4 },
        ];
        const rows = (projectScoped ? baseRows : baseRows.filter((r) => r.slug !== "design_review")).map(
          (r, idx) => ({
            id: `status-${r.slug}`,
            workspace_id: WORKSPACE_ID,
            project_id: projectScoped ? PROJECT_ID : null,
            name: r.name,
            slug: r.slug,
            category: r.category,
            color: r.color,
            icon: null,
            position: idx,
            is_default: r.slug === "backlog",
            is_active: true,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          }),
        );
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows) });
      },
    );

    await page.route(
      `${API_BASE}/workspaces/${WORKSPACE_ID}/status-categories**`,
      (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );
  });

  test("custom status appears as a kanban column on the project board", async ({ page }) => {
    await page.goto(`sprints/${PROJECT_ID}/board`);

    // The custom column heading is rendered as <h3>Design Review</h3>.
    await expect(page.getByRole("heading", { name: "Design Review" })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("table view toggle swaps the layout and persists per-project", async ({ page }) => {
    // Seed one task so the table has a row to render.
    await page.route(
      `${API_BASE}/sprints/${"sprint-1"}/tasks`,
      async (route) => {
        if (route.request().method() === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
              makeTask({
                id: "task-table-row",
                title: "Visible in both views",
                status: "todo",
              }),
            ]),
          });
          return;
        }
        await route.fallback();
      },
    );

    await page.goto(`sprints/${PROJECT_ID}/board`);

    // Default landing is Board.
    await expect(page.getByRole("heading", { name: "To Do" })).toBeVisible({
      timeout: 15_000,
    });

    // Toggle to Table.
    await page.getByRole("button", { name: /Table layout/i }).click();
    await expect(page.getByRole("columnheader", { name: /Title/i })).toBeVisible();
    await expect(page.getByText("Visible in both views")).toBeVisible();

    // Reload — preference should persist via localStorage scope `board:<id>`.
    await page.reload();
    await expect(page.getByRole("columnheader", { name: /Title/i })).toBeVisible();

    // Sanity: the persisted scope key matches what the hook writes.
    const stored = await page.evaluate(
      (k: string) => localStorage.getItem(k),
      `aexy:tasksLayout:board:${PROJECT_ID}`,
    );
    expect(stored).toBe("table");

    // Flip back to Board.
    await page.getByRole("button", { name: /Board layout/i }).click();
    await expect(page.getByRole("heading", { name: "To Do" })).toBeVisible();
  });
});
