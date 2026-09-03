import type { Metadata } from "next";
import "./globals.css";
import "./console.css";

export const metadata: Metadata = {
  title: "Central Auth Hub — Signal Room",
  description: "Identity, permissions and security operations console",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="th"><body>{children}</body></html>;
}
