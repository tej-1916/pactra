import type { Metadata } from "next";

import { CommerceConsole } from "@/components/commerce/CommerceConsole";
import { ALL_ROUTES } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";

export const metadata: Metadata = { title: "Live Commerce" };
export const dynamic = "force-dynamic";

/**
 * Live Commerce.
 *
 * A READ surface. It renders a real mission's offer, policy, authorization,
 * payment state and Decision Trace from the PACTRA API, and it contains no
 * control that changes state. The interactive checkout belongs to C5b and the
 * provider path to C2; neither is simulated here, because a demo that looks
 * like it moved money and did not is worse than one that plainly did not.
 */
export default function LiveCommercePage() {
  const blurb = ALL_ROUTES.find((item) => item.href === "/commerce")?.blurb;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Live Commerce"
        title="One transaction, from proposal to authority"
        description={blurb}
        actions={
          <Badge tone="neutral" variant="outline">
            READ-ONLY · C5a
          </Badge>
        }
      />
      <CommerceConsole />
    </div>
  );
}
