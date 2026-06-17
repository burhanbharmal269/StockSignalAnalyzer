import { PaperTradingView } from "@/features/paper-trading/paper-trading-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Paper Trading — ${APP_NAME}` };

export default function PaperTradingPage() {
  return <PaperTradingView />;
}
