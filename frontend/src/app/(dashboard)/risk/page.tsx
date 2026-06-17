import { RiskView } from "@/features/risk/risk-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Risk — ${APP_NAME}` };

export default function RiskPage() {
  return <RiskView />;
}
