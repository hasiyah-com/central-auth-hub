import { ConsoleFrame } from "@/components/ConsoleFrame";

export default function DeveloperLayout({ children }: { children: React.ReactNode }) {
  return <ConsoleFrame>{children}</ConsoleFrame>;
}
