import { LoginForm } from "@/features/auth/login-form";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Login — ${APP_NAME}` };

export default function LoginPage() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-md px-6">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold tracking-tight">{APP_NAME}</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Algorithmic Trading Control Center
          </p>
        </div>
        <LoginForm />
      </div>
    </main>
  );
}
