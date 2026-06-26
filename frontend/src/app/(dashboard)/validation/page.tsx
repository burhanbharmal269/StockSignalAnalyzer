import { ValidationView } from "@/features/validation/validation-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Validation — ${APP_NAME}` };

export default function ValidationPage() {
  return <ValidationView />;
}
