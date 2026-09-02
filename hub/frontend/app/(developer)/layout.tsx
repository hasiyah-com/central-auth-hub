import { Sidebar } from "@/components/Sidebar";
import { ConsoleFooter } from "@/components/ConsoleFooter";

export default function DeveloperLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <Sidebar />
      <div className="stage">
        {children}
        <ConsoleFooter />
      </div>
    </div>
  );
}
