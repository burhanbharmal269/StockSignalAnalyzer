import { CapitalView } from "@/features/capital/capital-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Capital Framework — ${APP_NAME}` };

export default function CapitalPage() {
  return <CapitalView />;
}
