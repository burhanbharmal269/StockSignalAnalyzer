import { StrategyAnalyticsView } from "@/features/signal-intelligence/strategy-analytics-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Strategy Analytics — ${APP_NAME}` };

export default function StrategyAnalyticsPage() {
  return <StrategyAnalyticsView />;
}
