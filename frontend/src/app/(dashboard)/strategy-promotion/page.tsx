import { StrategyPromotionView } from "@/features/strategy-promotion/strategy-promotion-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Strategy Promotion — ${APP_NAME}` };

export default function StrategyPromotionPage() {
  return <StrategyPromotionView />;
}
