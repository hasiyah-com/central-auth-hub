import { MockupConsole } from "@/components/mockup/MockupConsole";
import { notFound } from "next/navigation";

const MOCKUP_SCREEN_IDS = [
  "login",
  "dashboard",
  "users",
  "user-detail",
  "subsystems",
  "subsystem-detail",
  "requests",
  "permissions",
  "risk",
  "risk-detail",
  "audit",
  "settings",
] as const;

export function generateStaticParams() {
  return MOCKUP_SCREEN_IDS.map((screen) => ({ screen }));
}

export default function MockupPage({
  params,
}: {
  params: { screen: string };
}) {
  if (!MOCKUP_SCREEN_IDS.includes(params.screen as typeof MOCKUP_SCREEN_IDS[number])) {
    notFound();
  }

  return <MockupConsole screen={params.screen} />;
}
