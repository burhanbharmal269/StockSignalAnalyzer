import { SignalAnalyticsView } from "@/features/signal-intelligence/signal-analytics-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Signal Analytics — ${APP_NAME}` };

export default function SignalAnalyticsPage() {
  return <SignalAnalyticsView />;
}
