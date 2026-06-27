import { ResearchCommandCenter } from "@/features/research/research-command-center";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Research Command Center — ${APP_NAME}` };

export default function ResearchPage() {
  return (
    <div className="p-6">
      <ResearchCommandCenter />
    </div>
  );
}
