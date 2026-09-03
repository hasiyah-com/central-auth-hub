"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Heartbeat } from "@/components/Heartbeat";
import { Sidebar } from "@/components/Sidebar";
import { ConsoleFooter } from "@/components/ConsoleFooter";

/**
 * The published Signal Room intentionally has two shells:
 * - dashboard: the more expressive overview shell
 * - operational routes: the denser cx-* console shell
 *
 * Keeping that distinction is important. Reusing the dashboard shell for
 * every route changes the column width, spacing rhythm and page hierarchy.
 */
export function ConsoleFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const dashboard = pathname === "/dashboard";

  return (
    <div className={dashboard ? "shell" : "cx-shell"}>
      <Heartbeat />
      <Sidebar variant={dashboard ? "dashboard" : "compact"} />
      <div className={dashboard ? "stage" : "cx-stage"}>
        {children}
        {!dashboard && <ConsoleFooter variant="compact" />}
      </div>
    </div>
  );
}
