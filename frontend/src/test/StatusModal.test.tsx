import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

import { StatusModal } from "@/components/settings/StatusModal";
import type { WorkspaceStatusCategory } from "@/lib/api";

const CATEGORIES: WorkspaceStatusCategory[] = [
  {
    id: "cat-1",
    workspace_id: "ws-1",
    project_id: null,
    slug: "backlog",
    label: "Backlog",
    color: "#9CA3AF",
    semantics: "open",
    position: 0,
    is_default: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "cat-2",
    workspace_id: "ws-1",
    project_id: null,
    slug: "in_review",
    label: "In Review",
    color: "#8B5CF6",
    semantics: "active",
    position: 3,
    is_default: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

describe("StatusModal categories", () => {
  it("renders every category passed in via props", () => {
    render(
      <StatusModal
        status={null}
        categories={CATEGORIES}
        onClose={vi.fn()}
        onSave={vi.fn().mockResolvedValue(undefined)}
        isSaving={false}
      />,
    );

    expect(screen.getByText("Backlog")).toBeInTheDocument();
    expect(screen.getByText("In Review")).toBeInTheDocument();
    // Semantics label appears as the small uppercase hint.
    expect(screen.getAllByText(/open/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/active/i).length).toBeGreaterThan(0);
  });

  it("submits with the slug of the selected category", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <StatusModal
        status={null}
        categories={CATEGORIES}
        onClose={onClose}
        onSave={onSave}
        isSaving={false}
      />,
    );

    // Type a name + pick the second category.
    fireEvent.change(screen.getByPlaceholderText("In Review"), {
      target: { value: "Awaiting QA" },
    });
    fireEvent.click(screen.getByText("In Review").closest("button")!);

    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Awaiting QA",
        category: "in_review",
      }),
    );
  });

  it("shows the empty-state hint when no categories are supplied yet", () => {
    render(
      <StatusModal
        status={null}
        categories={[]}
        onClose={vi.fn()}
        onSave={vi.fn().mockResolvedValue(undefined)}
        isSaving={false}
      />,
    );
    expect(
      screen.getByText(/No categories defined yet/i),
    ).toBeInTheDocument();
  });
});
