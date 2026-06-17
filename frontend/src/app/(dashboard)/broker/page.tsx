import { BrokerView } from "@/features/broker/broker-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Broker — ${APP_NAME}` };

export default function BrokerPage() {
  return <BrokerView />;
}
