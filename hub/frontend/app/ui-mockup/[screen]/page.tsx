import { MockupConsole, MOCKUP_SCREENS } from "@/components/mockup/MockupConsole";
import { notFound } from "next/navigation";

export function generateStaticParams() {
  return Object.keys(MOCKUP_SCREENS).map((screen) => ({ screen }));
}

export default function MockupPage({ params }: { params: { screen: string } }) {
  if (!(params.screen in MOCKUP_SCREENS)) notFound();
  return <MockupConsole screen={params.screen} />;
}
