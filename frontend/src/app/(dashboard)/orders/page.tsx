import { OrdersView } from "@/features/orders/orders-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Orders — ${APP_NAME}` };

export default function OrdersPage() {
  return <OrdersView />;
}
