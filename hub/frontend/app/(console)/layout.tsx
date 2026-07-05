import { Sidebar } from "@/components/Sidebar";
import { PasskeyNudgeBanner } from "@/components/PasskeyNudgeBanner";

export default function ConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex bg-ink-50">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <PasskeyNudgeBanner accountHref="/account" />
        {children}
      </div>
    </div>
  );
}
