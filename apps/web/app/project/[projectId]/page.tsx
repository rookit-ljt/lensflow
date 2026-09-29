import { redirect } from "next/navigation";

type LegacyProjectPageProps = {
  params: Promise<{ projectId: string }>;
};

/** Keep links from older local sessions working after the route was pluralized. */
export default async function LegacyProjectPage({ params }: LegacyProjectPageProps) {
  const { projectId } = await params;
  redirect(`/projects/${projectId}`);
}
