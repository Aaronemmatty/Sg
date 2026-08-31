"use client";

import { useEffect } from "react";
import { Sidebar } from "./Sidebar";
import { useStore } from "@/lib/stores/app.store";
import { usePortfolioStream, useRiskStream, useExecutionStream } from "@/hooks/use-sse";
import type { User } from "@/types";

interface AppShellProps {
  user: User;
  children: React.ReactNode;
}

function SSEInitializer() {
  usePortfolioStream();
  useRiskStream();
  useExecutionStream();
  return null;
}

export function AppShell({ user, children }: AppShellProps) {
  const setUser = useStore((s) => s.setUser);

  useEffect(() => {
    setUser(user);
  }, [user, setUser]);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <SSEInitializer />
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {children}
      </main>
    </div>
  );
}
