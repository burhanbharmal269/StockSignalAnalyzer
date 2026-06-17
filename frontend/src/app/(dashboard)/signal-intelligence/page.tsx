import SignalIntelligenceView from "@/features/signal-intelligence/signal-intelligence-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Signal Intelligence — ${APP_NAME}` };

export default function SignalIntelligencePage() {
  return <SignalIntelligenceView />;
}
