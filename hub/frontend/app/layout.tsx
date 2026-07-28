import type { Metadata } from "next";
import "./globals.css";
import StepupTotpProvider from "@/components/StepupTotpProvider";

export const metadata: Metadata = {
  title: "Central Auth Hub — Admin",
  description: "ระบบจัดการสิทธิ์ผู้ใช้แบบศูนย์กลาง สำหรับมหาวิทยาลัย",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="th">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <StepupTotpProvider>{children}</StepupTotpProvider>
      </body>
    </html>
  );
}
