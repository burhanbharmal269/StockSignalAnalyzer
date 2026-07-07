import { FalsePositiveView } from "@/features/false-positive/false-positive-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `False Positive Analysis — ${APP_NAME}` };

export default function FalsePositivePage() {
  return <FalsePositiveView />;
}
