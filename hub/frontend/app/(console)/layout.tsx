import { Sidebar } from "@/components/Sidebar";
import { Heartbeat } from "@/components/Heartbeat";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="signal-shell flex min-h-screen">
      <Heartbeat />
      <Sidebar />
      <div className="signal-content flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
