import { RegimePerformanceView } from "@/features/regime-performance/regime-performance-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Regime Performance — ${APP_NAME}` };

export default function RegimePerformancePage() {
  return <RegimePerformanceView />;
}
