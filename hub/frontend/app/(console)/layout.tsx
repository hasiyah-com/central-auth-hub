import { ConsoleFrame } from "@/components/ConsoleFrame";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return <ConsoleFrame>{children}</ConsoleFrame>;
}
