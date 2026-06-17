import { PortfoliosView } from "@/features/capital/portfolios-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Portfolios — ${APP_NAME}` };

export default function PortfoliosPage() {
  return <PortfoliosView />;
}
