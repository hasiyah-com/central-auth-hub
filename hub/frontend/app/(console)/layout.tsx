import { Sidebar } from "@/components/Sidebar";
import { ConsoleFooter } from "@/components/ConsoleFooter";
import { Heartbeat } from "@/components/Heartbeat";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <Heartbeat />
      <Sidebar />
      <div className="stage">
        {children}
        <ConsoleFooter />
      </div>
    </div>
  );
}
