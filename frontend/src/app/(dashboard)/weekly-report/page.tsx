import WeeklyReportView from "@/features/analytics-intelligence/weekly-report-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Weekly Intelligence Report — ${APP_NAME}` };

export default function WeeklyReportPage() {
  return <WeeklyReportView />;
}
