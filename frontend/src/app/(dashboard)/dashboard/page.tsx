import { DashboardView } from "@/features/dashboard/dashboard-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Dashboard — ${APP_NAME}` };

export default function DashboardPage() {
  return <DashboardView />;
}
