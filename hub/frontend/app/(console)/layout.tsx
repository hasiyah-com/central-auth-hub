import { Sidebar } from "@/components/Sidebar";
import { SecurityOnboarding } from "@/components/SecurityOnboarding";
import { Heartbeat } from "@/components/Heartbeat";

export default function ConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex bg-ink-50">
      <Heartbeat />
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <SecurityOnboarding accountHref="/account" />
        {children}
      </div>
    </div>
  );
}
