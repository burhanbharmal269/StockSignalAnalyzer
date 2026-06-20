import PostTradeView from "@/features/analytics-intelligence/post-trade-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Post-Trade Intelligence — ${APP_NAME}` };

export default function PostTradePage() {
  return <PostTradeView />;
}
