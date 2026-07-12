import { describe, it, expect } from "vitest";
import { GROUPED_LAYOUT, FLAT_LAYOUT, SidebarSectionConfig } from "@/config/sidebarLayouts";
import { CRM_NAV_ITEMS } from "./fixtures";

function findCrmSection(sections: SidebarSectionConfig[]) {
  for (const section of sections) {
    const match = section.items.find((item) => item.href === "/crm");
    if (match) return match;
  }
  return undefined;
}

describe.each([
  ["GROUPED_LAYOUT", GROUPED_LAYOUT],
  ["FLAT_LAYOUT", FLAT_LAYOUT],
])("CRM navigation shell — %s", (_name, layout) => {
  it("has a top-level CRM entry with the expected sub-items", () => {
    const crm = findCrmSection(layout.sections);
    expect(crm).toBeDefined();
    expect(crm?.items?.map((i) => ({ href: i.href, label: i.label }))).toEqual(
      CRM_NAV_ITEMS.map((i) => ({ href: i.href, label: i.label }))
    );
  });

  it("scopes the CRM entry to business personas when personas are declared", () => {
    const crm = findCrmSection(layout.sections);
    if (crm?.personas) {
      expect(crm.personas).toEqual(expect.arrayContaining(["sales", "support", "admin"]));
    }
  });
});

describe("CRM sub-nav items", () => {
  it("all hrefs are unique", () => {
    const hrefs = CRM_NAV_ITEMS.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("all hrefs live under the /crm base route", () => {
    for (const item of CRM_NAV_ITEMS) {
      expect(item.href === "/crm" || item.href.startsWith("/crm/")).toBe(true);
    }
  });
});
