import { Sidebar } from "@/components/layout/sidebar";
import { TopNav } from "@/components/layout/top-nav";
import { SessionWarningBanner } from "@/components/shared/session-warning-banner";
import { WebSocketProvider } from "@/providers/websocket-provider";
import { ErrorBoundary } from "@/components/shared/error-boundary";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <WebSocketProvider>
      <div className="flex h-screen overflow-hidden bg-background">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0">
          <TopNav />
          <SessionWarningBanner />
          <main className="flex-1 overflow-y-auto p-6">
            <ErrorBoundary>{children}</ErrorBoundary>
          </main>
        </div>
      </div>
    </WebSocketProvider>
  );
}
