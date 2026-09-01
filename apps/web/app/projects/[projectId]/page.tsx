import { AuthGate } from "@/components/auth/auth-gate";

type ProjectPageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function ProjectPage({ params }: ProjectPageProps) {
  const { projectId } = await params;
  return <AuthGate projectId={projectId} />;
}
