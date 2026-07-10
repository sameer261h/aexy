import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RelationshipRecordChip } from "@/components/crm/relationships/RelationshipRecordChip";
import { RelatedRecordSummary } from "@/lib/api";

const accessible: RelatedRecordSummary = {
  attribute_id: "attr-1",
  record_id: "rec-1",
  accessible: true,
  object_id: "obj-1",
  object_label: "Company",
  record_label: "Acme Corp",
  is_archived: false,
};

const inaccessible: RelatedRecordSummary = {
  attribute_id: "attr-1",
  record_id: "rec-stale",
  accessible: false,
  object_id: null,
  object_label: null,
  record_label: null,
  is_archived: null,
};

describe("RelationshipRecordChip", () => {
  it("renders the resolved label instead of the raw record ID", () => {
    render(<RelationshipRecordChip summary={accessible} objectSlug="companies" />);
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.queryByText("rec-1")).not.toBeInTheDocument();
  });

  it("fires onClick when clicked and an object slug is resolved", () => {
    const onClick = vi.fn();
    render(<RelationshipRecordChip summary={accessible} objectSlug="companies" onClick={onClick} />);
    fireEvent.click(screen.getByText("Acme Corp"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders an opaque placeholder for inaccessible references, never a label", () => {
    render(<RelationshipRecordChip summary={inaccessible} />);
    expect(screen.getByText("Unavailable reference")).toBeInTheDocument();
    expect(screen.queryByText("rec-stale")).not.toBeInTheDocument();
  });

  it("does not navigate for inaccessible references even if onClick is passed", () => {
    const onClick = vi.fn();
    render(<RelationshipRecordChip summary={inaccessible} onClick={onClick} />);
    fireEvent.click(screen.getByText("Unavailable reference"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("is non-clickable when no object slug has resolved yet, even if accessible", () => {
    const onClick = vi.fn();
    render(<RelationshipRecordChip summary={accessible} onClick={onClick} />);
    const button = screen.getByText("Acme Corp").closest("button");
    expect(button).toBeDisabled();
  });
});
