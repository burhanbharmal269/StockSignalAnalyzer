import { ParameterOptimizationView } from "@/features/parameter-optimization/parameter-optimization-view";
import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `Parameter Optimization — ${APP_NAME}` };

export default function ParameterOptimizationPage() {
  return <ParameterOptimizationView />;
}
