import { AuthGate } from "@/components/auth/auth-gate";

export default function DashboardPage() {
  return <AuthGate />;
}
