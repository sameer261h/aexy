"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, Suspense } from "react";
import { NextIntlClientProvider } from "next-intl";
import { NavigationProgress } from "@/components/ui/navigation-progress";
import { OAuthInflightTagger } from "@/components/OAuthInflightTagger";
import { ThemeProvider } from "@/components/ThemeProvider";
import { useLocaleStore } from "@/stores/localeStore";

export function Providers({
  children,
  messages,
  serverLocale,
}: {
  children: React.ReactNode;
  messages: Record<string, unknown>;
  serverLocale: string;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return (
    <NextIntlClientProvider locale={serverLocale} messages={messages}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <Suspense fallback={null}>
            <NavigationProgress />
          </Suspense>
          <OAuthInflightTagger />
          {children}
        </ThemeProvider>
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
}
