import { Sidebar } from "@/components/Sidebar";
import { ConsoleFooter } from "@/components/ConsoleFooter";

export default function DeveloperLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="signal-shell flex min-h-screen">
      <Sidebar />
      <div className="signal-content flex min-w-0 flex-1 flex-col">
        {children}
        <ConsoleFooter />
      </div>
    </div>
  );
}
