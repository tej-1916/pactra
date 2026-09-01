import type { Metadata } from "next";

import { CommerceConsole } from "@/components/commerce/CommerceConsole";
import { ALL_ROUTES } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { PageContainer } from "@/components/ui/PageContainer";
import { Badge } from "@/components/ui/Badge";

export const metadata: Metadata = { title: "Live Commerce Workbench" };
export const dynamic = "force-dynamic";

export default function LiveCommercePage() {
  const blurb = ALL_ROUTES.find((item) => item.href === "/commerce")?.blurb;

  return (
    <PageContainer variant="wide" className="space-y-6">
      <PageHeader
        eyebrow="LIVE COMMERCE WORKBENCH"
        title="Follow an AI purchase through deterministic controls"
        description={blurb || "Inspect the complete transaction journey from AI proposal to deterministic binding and payment settlement."}
        actions={
          <Badge tone="accent" variant="outline">
            INTERACTIVE WORKBENCH
          </Badge>
        }
      />
      <CommerceConsole />
    </PageContainer>
  );
}
