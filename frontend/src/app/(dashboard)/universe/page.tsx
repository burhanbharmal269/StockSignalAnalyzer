import { UniverseView } from "@/features/universe/universe-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Universe — ${APP_NAME}` };

export default function UniversePage() {
  return <UniverseView />;
}
