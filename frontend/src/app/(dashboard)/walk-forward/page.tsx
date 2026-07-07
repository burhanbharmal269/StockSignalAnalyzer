import { WalkForwardView } from "@/features/walk-forward/walk-forward-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Walk-Forward Analysis — ${APP_NAME}` };

export default function WalkForwardPage() {
  return <WalkForwardView />;
}
