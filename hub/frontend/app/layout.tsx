import type { Metadata } from "next";
import "./globals.css";
import "./signal-dashboard.css";
import StepupTotpProvider from "@/components/StepupTotpProvider";

export const metadata: Metadata = {
  title: "Central Auth Hub — Signal Room",
  description: "ระบบจัดการตัวตน สิทธิ์ และการเฝ้าระวังความปลอดภัยแบบศูนย์กลาง",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Anuphan:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Thai:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <StepupTotpProvider>{children}</StepupTotpProvider>
      </body>
    </html>
  );
}
