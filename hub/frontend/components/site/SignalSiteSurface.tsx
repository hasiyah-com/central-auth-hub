"use client";

import { usePathname } from "next/navigation";
import SignalDashboard from "@/components/site/SignalDashboard";
import { ConsoleRouter } from "@/components/site/ConsolePages";
import Heartbeat from "@/components/Heartbeat";

export function SignalSiteSurface() {
  const pathname = usePathname();
  return <><Heartbeat />{pathname === "/dashboard" ? <SignalDashboard /> : <ConsoleRouter />}</>;
}
