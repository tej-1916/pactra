import type { Metadata } from "next";

import { MissionDetail } from "@/components/mission/MissionDetail";

export const metadata: Metadata = { title: "Mission" };

export default async function MissionDetailPage({
  params,
}: {
  params: Promise<{ missionId: string }>;
}) {
  const { missionId } = await params;
  return <MissionDetail missionId={missionId} />;
}
