import { SettingsView } from "@/features/settings/settings-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Settings — ${APP_NAME}` };

export default function SettingsPage() {
  return <SettingsView />;
}
