import PortfolioIntelligenceView from "@/features/analytics-intelligence/portfolio-intelligence-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Portfolio Intelligence — ${APP_NAME}` };

export default function PortfolioIntelligencePage() {
  return <PortfolioIntelligenceView />;
}
