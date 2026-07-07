import { ResearchHubView } from "@/features/research-hub/research-hub-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Research Hub — ${APP_NAME}` };

export default function ResearchHubPage() {
  return <ResearchHubView />;
}
