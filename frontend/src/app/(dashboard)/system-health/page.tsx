import { SystemHealthView } from "@/features/system-health/system-health-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `System Health — ${APP_NAME}` };

export default function SystemHealthPage() {
  return <SystemHealthView />;
}
