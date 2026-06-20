import ResearchView from "@/features/analytics-intelligence/research-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Research Intelligence — ${APP_NAME}` };

export default function ResearchPage() {
  return <ResearchView />;
}
