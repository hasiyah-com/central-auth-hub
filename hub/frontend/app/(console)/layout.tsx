import { Sidebar } from "@/components/Sidebar";
import { ConsoleFooter } from "@/components/ConsoleFooter";
import { Heartbeat } from "@/components/Heartbeat";
import { IdleSessionGuard } from "@/components/IdleSessionGuard";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="signal-shell flex min-h-screen">
      <Heartbeat />
      <IdleSessionGuard />
      <Sidebar />
      <div className="signal-content flex min-w-0 flex-1 flex-col">
        {children}
        <ConsoleFooter />
      </div>
    </div>
  );
}
