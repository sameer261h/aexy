import { describe, it, expect } from "vitest";
import { getAppIdFromPath } from "@/config/appDefinitions";
import { CRM_ROUTES_RESOLVING_TO_APP } from "./fixtures";

describe("getAppIdFromPath — CRM routes", () => {
  it.each(CRM_ROUTES_RESOLVING_TO_APP)("resolves %s to the crm app", (route) => {
    expect(getAppIdFromPath(route)).toBe("crm");
  });

  it("does not resolve unrelated top-level routes to crm", () => {
    expect(getAppIdFromPath("/agents")).not.toBe("crm");
    expect(getAppIdFromPath("/booking")).not.toBe("crm");
    expect(getAppIdFromPath("/dashboard")).not.toBe("crm");
  });
});
