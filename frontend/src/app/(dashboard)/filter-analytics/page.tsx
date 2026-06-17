import { FilterAnalyticsView } from "@/features/signal-intelligence/filter-analytics-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Filter Analytics — ${APP_NAME}` };

export default function FilterAnalyticsPage() {
  return <FilterAnalyticsView />;
}
