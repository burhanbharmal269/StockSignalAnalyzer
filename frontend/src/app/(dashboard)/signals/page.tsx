import { SignalsView } from "@/features/signals/signals-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Signals — ${APP_NAME}` };

export default function SignalsPage() {
  return <SignalsView />;
}
