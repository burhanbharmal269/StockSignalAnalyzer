import { AnalyticsView } from "@/features/analytics/analytics-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Analytics — ${APP_NAME}` };

export default function AnalyticsPage() {
  return <AnalyticsView />;
}
