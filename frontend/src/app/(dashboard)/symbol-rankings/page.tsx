import { SymbolRankingsView } from "@/features/symbol-rankings/symbol-rankings-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Symbol Rankings — ${APP_NAME}` };

export default function SymbolRankingsPage() {
  return <SymbolRankingsView />;
}
