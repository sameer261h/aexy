import { describe, it, expect } from "vitest";
import { applyPersonComputedColumns } from "@/app/(app)/crm/[objectSlug]/page";
import { CRMRecord, CRMAttribute, CRMObjectType } from "@/lib/api";

function makeRecord(overrides: Partial<CRMRecord> = {}): CRMRecord {
  return {
    id: "rec_1",
    workspace_id: "ws_1",
    object_id: "obj_1",
    values: { name: "Test", email: "test@example.com" },
    display_name: "Test",
    owner_id: null,
    created_by_id: null,
    is_archived: false,
    archived_at: null,
    computed: null,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeAttribute(overrides: Partial<CRMAttribute> = {}): CRMAttribute {
  return {
    id: "attr_1",
    object_id: "obj_1",
    name: "Email",
    slug: "email",
    attribute_type: "email",
    description: null,
    is_required: false,
    is_unique: false,
    is_searchable: true,
    is_filterable: true,
    is_sortable: true,
    is_system: false,
    config: {},
    default_value: null,
    order: 0,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("applyPersonComputedColumns", () => {
  const personType: CRMObjectType = "person";
  const companyType: CRMObjectType = "company";

  describe("for person objects", () => {
    it("adds three synthesized attributes to the array", () => {
      const records = [makeRecord()];
      const attrs = [makeAttribute()];
      const result = applyPersonComputedColumns(records, attrs, personType);

      expect(result.attributes).toHaveLength(4);
      const slugs = result.attributes.map((a) => a.slug);
      expect(slugs).toEqual([
        "email",
        "__last_email_interaction",
        "__last_calendar_interaction",
        "__connection_strength",
      ]);
    });

    it("synthesized attributes have correct types and config", () => {
      const records = [makeRecord()];
      const attrs: CRMAttribute[] = [];
      const result = applyPersonComputedColumns(records, attrs, personType);

      const emailAttr = result.attributes.find((a) => a.slug === "__last_email_interaction")!;
      expect(emailAttr).toBeDefined();
      expect(emailAttr.attribute_type).toBe("timestamp");
      expect(emailAttr.name).toBe("Last email interaction");
      expect(emailAttr.is_system).toBe(true);
      expect(emailAttr.is_filterable).toBe(false);

      const calAttr = result.attributes.find((a) => a.slug === "__last_calendar_interaction")!;
      expect(calAttr).toBeDefined();
      expect(calAttr.attribute_type).toBe("timestamp");
      expect(calAttr.name).toBe("Last calendar interaction");

      const strengthAttr = result.attributes.find((a) => a.slug === "__connection_strength")!;
      expect(strengthAttr).toBeDefined();
      expect(strengthAttr.attribute_type).toBe("status");
      expect(strengthAttr.name).toBe("Connection strength");
      expect(strengthAttr.config).toEqual({
        options: [
          { value: "weak", label: "Weak", color: "#f59e0b" },
          { value: "good", label: "Good", color: "#3b82f6" },
          { value: "strong", label: "Strong", color: "#3b82f6" },
          { value: "very_strong", label: "Very Strong", color: "#22c55e" },
        ],
      });
    });

    it("injects computed values into record.values for each record", () => {
      const records = [
        makeRecord({
          id: "rec_1",
          computed: {
            last_email_interaction: "2025-06-01T12:00:00Z",
            last_calendar_interaction: "2025-06-02T12:00:00Z",
            connection_strength: "strong",
          },
        }),
        makeRecord({
          id: "rec_2",
          computed: {
            last_email_interaction: "2025-05-01T12:00:00Z",
            last_calendar_interaction: null,
            connection_strength: "weak",
          },
        }),
      ];
      const attrs: CRMAttribute[] = [];
      const result = applyPersonComputedColumns(records, attrs, personType);

      const r1 = result.records.find((r) => r.id === "rec_1")!;
      expect(r1.values.__last_email_interaction).toBe("2025-06-01T12:00:00Z");
      expect(r1.values.__last_calendar_interaction).toBe("2025-06-02T12:00:00Z");
      expect(r1.values.__connection_strength).toBe("strong");

      const r2 = result.records.find((r) => r.id === "rec_2")!;
      expect(r2.values.__last_email_interaction).toBe("2025-05-01T12:00:00Z");
      expect(r2.values.__last_calendar_interaction).toBeNull();
      expect(r2.values.__connection_strength).toBe("weak");
    });

    it("maps null computed to null values (no crash)", () => {
      const records = [makeRecord({ computed: null })];
      const attrs: CRMAttribute[] = [];
      const result = applyPersonComputedColumns(records, attrs, personType);

      const r = result.records[0];
      expect(r.values.__last_email_interaction).toBeNull();
      expect(r.values.__last_calendar_interaction).toBeNull();
      expect(r.values.__connection_strength).toBeNull();
    });

    it("maps missing computed (undefined) to null values (no crash)", () => {
      const records = [makeRecord({ computed: undefined })];
      const attrs: CRMAttribute[] = [];
      const result = applyPersonComputedColumns(records, attrs, personType);

      const r = result.records[0];
      expect(r.values.__last_email_interaction).toBeNull();
      expect(r.values.__last_calendar_interaction).toBeNull();
      expect(r.values.__connection_strength).toBeNull();
    });

    it("preserves existing record.values", () => {
      const records = [
        makeRecord({
          values: { name: "Alice", email: "alice@example.com", department: "Engineering" },
        }),
      ];
      const result = applyPersonComputedColumns(records, [], personType);

      const r = result.records[0];
      expect(r.values.name).toBe("Alice");
      expect(r.values.email).toBe("alice@example.com");
      expect(r.values.department).toBe("Engineering");
    });
  });

  describe("for non-person objects", () => {
    it("returns records and attributes unchanged for company", () => {
      const records = [makeRecord()];
      const attrs = [makeAttribute()];
      const result = applyPersonComputedColumns(records, attrs, companyType);

      expect(result.records).toBe(records);
      expect(result.attributes).toBe(attrs);
      expect(result.attributes).toHaveLength(1);
    });

    it("does not inject computed values for deal objects", () => {
      const records = [makeRecord({ computed: { last_email_interaction: "2025-06-01T12:00:00Z", last_calendar_interaction: null, connection_strength: "good" } })];
      const attrs: CRMAttribute[] = [];
      const result = applyPersonComputedColumns(records, attrs, "deal");

      expect(result.attributes).toHaveLength(0);
      expect(result.records[0].values.__last_email_interaction).toBeUndefined();
    });

    it("returns empty arrays when empty arrays are passed for company", () => {
      const result = applyPersonComputedColumns([], [], companyType);

      expect(result.records).toEqual([]);
      expect(result.attributes).toEqual([]);
    });
  });
});
