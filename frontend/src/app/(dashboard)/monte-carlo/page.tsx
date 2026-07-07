import { MonteCarloView } from "@/features/monte-carlo/monte-carlo-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Monte Carlo — ${APP_NAME}` };

export default function MonteCarloPage() {
  return <MonteCarloView />;
}
