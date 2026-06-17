import { PositionsView } from "@/features/positions/positions-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Positions — ${APP_NAME}` };

export default function PositionsPage() {
  return <PositionsView />;
}
