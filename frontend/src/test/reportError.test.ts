/**
 * TDD spec for `reportError` (UX-LE-005).
 *
 * The frontend has Next.js error boundaries (ModuleError) that
 * receive `error.digest` from React's server-component error path.
 * Today they render a friendly UI but the digest goes nowhere — so
 * an operator can't actually look up the underlying server error in
 * production logs without grepping by hand.
 *
 * `reportError` is a thin bridge:
 *
 * - If `window.Sentry?.captureException` is available, forward the
 *   error + the digest + any contextual tags so the Sentry issue
 *   page surfaces them.
 * - Otherwise, console.error with a sentinel prefix so the same
 *   info is at least visible in DevTools.
 * - Safe to call from server-rendered components (no `window`).
 *   No-op in that case rather than crashing.
 *
 * The contract here is small but load-bearing: ModuleError fires
 * this on mount, and shipping the wrong shape would silently swallow
 * production errors.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { reportError } from "@/lib/reportError";


beforeEach(() => {
  // Reset any global Sentry we might have stubbed in.
  delete (globalThis as { Sentry?: unknown }).Sentry;
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});


afterEach(() => {
  vi.restoreAllMocks();
});


describe("reportError — Sentry available", () => {
  it("forwards the error to Sentry.captureException", () => {
    const captureSpy = vi.fn();
    (globalThis as { Sentry?: unknown }).Sentry = { captureException: captureSpy };

    const err = new Error("boom");
    reportError(err);

    expect(captureSpy).toHaveBeenCalledTimes(1);
    expect(captureSpy.mock.calls[0][0]).toBe(err);
  });

  it("attaches digest as a tag when provided", () => {
    const captureSpy = vi.fn();
    (globalThis as { Sentry?: unknown }).Sentry = { captureException: captureSpy };

    reportError(new Error("boom"), { digest: "abc123" });

    const opts = captureSpy.mock.calls[0][1];
    expect(opts?.tags?.digest).toBe("abc123");
  });

  it("attaches context tags when provided", () => {
    const captureSpy = vi.fn();
    (globalThis as { Sentry?: unknown }).Sentry = { captureException: captureSpy };

    reportError(new Error("boom"), {
      digest: "abc123",
      context: { module: "agents", agent_id: "a1" },
    });

    const opts = captureSpy.mock.calls[0][1];
    expect(opts?.tags?.module).toBe("agents");
    expect(opts?.tags?.agent_id).toBe("a1");
    // Digest still present.
    expect(opts?.tags?.digest).toBe("abc123");
  });

  it("survives a Sentry that throws", () => {
    (globalThis as { Sentry?: unknown }).Sentry = {
      captureException: () => {
        throw new Error("Sentry transport failed");
      },
    };

    // Must not propagate — error reporting must never crash the
    // already-erroring boundary.
    expect(() => reportError(new Error("boom"))).not.toThrow();
    // And falls back to console so the operator still sees it.
    expect(console.error).toHaveBeenCalled();
  });
});


describe("reportError — Sentry absent", () => {
  it("logs to console.error with a sentinel prefix", () => {
    const err = new Error("boom");
    reportError(err);

    expect(console.error).toHaveBeenCalled();
    const firstArg = (console.error as ReturnType<typeof vi.spyOn>).mock.calls[0][0];
    // Prefix is what an operator greps logs for — pin it.
    expect(firstArg).toContain("[reportError]");
  });

  it("includes digest in the console output when provided", () => {
    reportError(new Error("boom"), { digest: "abc123" });

    const args = (console.error as ReturnType<typeof vi.spyOn>).mock.calls[0];
    // The digest rides in a `{ digest: '...' }` object — JSON.stringify
    // each arg so the substring check sees inside objects.
    const allArgs = args.map((a: unknown) => JSON.stringify(a)).join(" ");
    expect(allArgs).toContain("abc123");
  });

  it("includes context in the console output when provided", () => {
    reportError(new Error("boom"), {
      context: { module: "agents", agent_id: "a1" },
    });

    const args = (console.error as ReturnType<typeof vi.spyOn>).mock.calls[0];
    const allArgs = args.map((a: unknown) => JSON.stringify(a)).join(" ");
    expect(allArgs).toContain("agents");
    expect(allArgs).toContain("a1");
  });
});


describe("reportError — non-Error values", () => {
  it("accepts plain strings", () => {
    expect(() => reportError("something went wrong")).not.toThrow();
    expect(console.error).toHaveBeenCalled();
  });

  it("accepts unknown values", () => {
    expect(() => reportError({ weird: "object" })).not.toThrow();
    expect(() => reportError(null)).not.toThrow();
    expect(() => reportError(undefined)).not.toThrow();
  });
});


describe("reportError — SSR safety", () => {
  it("no-ops when window is undefined (SSR)", () => {
    // Vitest's jsdom env defines window, so simulate SSR by
    // temporarily removing it.
    const savedWindow = global.window;
    // @ts-expect-error — intentionally undefining for the test.
    delete global.window;
    try {
      expect(() => reportError(new Error("server error"))).not.toThrow();
    } finally {
      global.window = savedWindow;
    }
  });
});
