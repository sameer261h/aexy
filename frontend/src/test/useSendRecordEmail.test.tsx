import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const sendEmailMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api", () => ({
  crmApi: {
    records: {
      sendEmail: (...args: unknown[]) => sendEmailMock(...args),
    },
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

import { useSendRecordEmail } from "@/hooks/useCRM";

const WORKSPACE = "workspace-1";
const OBJECT = "people-1";
const RECORD = "person-1";

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

describe("useSendRecordEmail", () => {
  beforeEach(() => {
    sendEmailMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("uses the record-scoped endpoint and refreshes the activity feed after send", async () => {
    sendEmailMock.mockResolvedValue({
      message_id: "gmail-1",
      thread_id: null,
      sent_to: "person@example.test",
    });
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(
      () => useSendRecordEmail(WORKSPACE, OBJECT, RECORD),
      { wrapper: makeWrapper(client) },
    );

    await result.current.sendEmail({ subject: "Hello", body_html: "Body" });

    expect(sendEmailMock).toHaveBeenCalledWith(WORKSPACE, OBJECT, RECORD, {
      subject: "Hello",
      body_html: "Body",
    });
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["crmActivities", WORKSPACE, RECORD],
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Email sent");
  });
});
