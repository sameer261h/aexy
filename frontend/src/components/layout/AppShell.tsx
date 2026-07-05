"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "./Sidebar";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/ErrorBoundary";

interface AppShellProps {
    children: React.ReactNode;
    user?: {
        name?: string | null;
        email?: string | null;
    } | null;
    logout?: () => void;
}

import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Menu } from "lucide-react";
import { Button } from "../ui/button";

export function AppShell({ children, user, logout }: AppShellProps) {
    // Chromeless / embedded mode for the macOS desktop app: when loaded with
    // ?embed=true the native app's own sidebar is the navigation, so we hide the
    // web sidebar + mobile header and render content full-width. The flag is
    // persisted so client-side route changes within the embed stay chromeless.
    const [embedded, setEmbedded] = useState(false);
    useEffect(() => {
        try {
            const isEmbed =
                new URLSearchParams(window.location.search).get("embed") === "true" ||
                window.localStorage.getItem("aexy_embed") === "1";
            if (isEmbed) {
                window.localStorage.setItem("aexy_embed", "1");
                setEmbedded(true);
            }
        } catch {
            /* SSR / no storage — render normal chrome */
        }
    }, []);

    return (
        <div className="flex h-screen overflow-hidden bg-background">
            {/* UX-A11Y-007: skip-to-content link. Hidden until focused;
                keyboard users can Tab once on page load and jump past
                the sidebar + header straight into #main-content. Helps
                screen readers and motor-impaired users avoid the 30+
                tab stops in the sidebar. */}
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[60] focus:px-3 focus:py-2 focus:rounded-lg focus:bg-purple-600 focus:text-white focus:shadow-lg focus-visible:ring-2 focus-visible:ring-purple-300"
            >
                Skip to main content
            </a>
            {/* Mobile Navigation */}
            {!embedded && (
                <header className="md:hidden fixed top-0 left-0 right-0 z-40 flex items-center h-16 px-4 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
                    <Sheet>
                        <SheetTrigger asChild>
                            <Button variant="ghost" size="icon" className="mr-2">
                                <Menu className="h-5 w-5" />
                                <span className="sr-only">Toggle menu</span>
                            </Button>
                        </SheetTrigger>
                        <SheetContent side="left" className="p-0 w-[240px] max-w-[85vw]">
                            <Sidebar user={user} logout={logout} className="border-none w-full h-full" />
                        </SheetContent>
                    </Sheet>
                    <div className="font-semibold text-lg">Aexy</div>
                </header>
            )}

            {!embedded && <Sidebar user={user} logout={logout} className="hidden md:flex" />}
            <main
                id="main-content"
                tabIndex={-1}
                className={cn(
                    "flex-1 overflow-y-auto focus:outline-none",
                    embedded ? "pt-0" : "md:pt-0 pt-16"
                )}
            >
                <div className="mx-0 p-0">
                    <ErrorBoundary>
                        {children}
                    </ErrorBoundary>
                </div>
            </main>
        </div>
    );
}
