import { Sidebar } from "@/components/Sidebar";
import { PasskeyNudgeBanner } from "@/components/PasskeyNudgeBanner";

export default function DeveloperLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex bg-ink-50">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <PasskeyNudgeBanner accountHref="/developer/account" />
        {children}
      </div>
    </div>
  );
}
