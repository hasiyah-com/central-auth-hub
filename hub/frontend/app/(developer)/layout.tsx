import { Sidebar } from "@/components/Sidebar";

// การ์ด "เพิ่มความปลอดภัย" ย้ายไปเป็นหน้า interstitial /auth/setup แล้ว (แสดงครั้งเดียวหลัง login)
export default function DeveloperLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex bg-ink-50">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">{children}</div>
    </div>
  );
}
