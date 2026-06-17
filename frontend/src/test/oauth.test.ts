import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  safeInternalPath,
  stashPostLoginRedirect,
  consumePostLoginRedirect,
  POST_LOGIN_REDIRECT_KEY,
  OAUTH_INFLIGHT_KEY,
  markOAuthInflight,
  consumeOAuthInflight,
} from "@/lib/oauth";

// JSDOM-style sessionStorage is provided automatically when running under
// vitest's jsdom environment. We clear it between tests so assertions
// don't bleed across cases.

beforeEach(() => {
  if (typeof window !== "undefined") {
    window.sessionStorage.clear();
  }
});

describe("safeInternalPath", () => {
  it("accepts a normal internal path", () => {
    expect(safeInternalPath("/dashboard")).toBe("/dashboard");
    expect(safeInternalPath("/sprints/123")).toBe("/sprints/123");
  });

  it("rejects protocol-relative URLs (open-redirect vector)", () => {
    expect(safeInternalPath("//evil.com")).toBeNull();
    expect(safeInternalPath("//evil.com/path")).toBeNull();
  });

  it("rejects absolute URLs", () => {
    expect(safeInternalPath("https://evil.com")).toBeNull();
    expect(safeInternalPath("http://evil.com/login")).toBeNull();
  });

  it("rejects junk and empty values", () => {
    expect(safeInternalPath(null)).toBeNull();
    expect(safeInternalPath(undefined)).toBeNull();
    expect(safeInternalPath("")).toBeNull();
    expect(safeInternalPath("dashboard")).toBeNull();
    expect(safeInternalPath("/\\evil.com")).toBeNull();
  });
});

describe("stashPostLoginRedirect / consumePostLoginRedirect", () => {
  it("round-trips a safe path", () => {
    stashPostLoginRedirect("/sprints");
    expect(window.sessionStorage.getItem(POST_LOGIN_REDIRECT_KEY)).toBe("/sprints");
    expect(consumePostLoginRedirect()).toBe("/sprints");
    // consume removes the entry
    expect(window.sessionStorage.getItem(POST_LOGIN_REDIRECT_KEY)).toBeNull();
  });

  it("silently drops unsafe paths so they never reach sessionStorage", () => {
    stashPostLoginRedirect("//evil.com");
    expect(window.sessionStorage.getItem(POST_LOGIN_REDIRECT_KEY)).toBeNull();
    expect(consumePostLoginRedirect()).toBeNull();
  });

  it("consume returns null when nothing was stashed", () => {
    expect(consumePostLoginRedirect()).toBeNull();
  });
});

describe("markOAuthInflight / consumeOAuthInflight", () => {
  it("round-trips and clears", () => {
    markOAuthInflight();
    expect(window.sessionStorage.getItem(OAUTH_INFLIGHT_KEY)).toBe("1");
    expect(consumeOAuthInflight()).toBe(true);
    expect(window.sessionStorage.getItem(OAUTH_INFLIGHT_KEY)).toBeNull();
  });

  it("returns false when no marker is set", () => {
    expect(consumeOAuthInflight()).toBe(false);
  });
});
