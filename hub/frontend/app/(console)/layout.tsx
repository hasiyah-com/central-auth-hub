import { Sidebar } from "@/components/Sidebar";
import { Heartbeat } from "@/components/Heartbeat";

// หมายเหตุ: การ์ด "เพิ่มความปลอดภัย" ย้ายไปเป็นหน้า interstitial /auth/setup
// (แสดงครั้งเดียวหลัง login) แล้ว — ไม่ฝังเป็น banner ทุกหน้าอีก
export default function ConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex bg-ink-50">
      <Heartbeat />
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">{children}</div>
    </div>
  );
}
