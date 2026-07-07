import { StrategyVersionsView } from "@/features/strategy-versions/strategy-versions-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Strategy Versions — ${APP_NAME}` };

export default function StrategyVersionsPage() {
  return <StrategyVersionsView />;
}
