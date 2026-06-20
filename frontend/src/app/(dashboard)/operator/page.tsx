import OperatorView from "@/features/analytics-intelligence/operator-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Operator Status — ${APP_NAME}` };

export default function OperatorPage() {
  return <OperatorView />;
}
