"use client";

import { Activity } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { ResultBoundary } from "@/components/ui/ResultBoundary";
import { DataTierBadge } from "@/components/ui/DataTier";
import { useHealth } from "@/lib/hooks/queries";

/**
 * Live system status on the overview.
 *
 * `payment_test_mode` is read from the process rather than hardcoded, because
 * the assertion "no real money moves" is only worth making if it comes from the
 * thing that would otherwise be moving it. When the API cannot be reached this
 * renders as unavailable — never as a quiet green.
 */
export function SystemStatus() {
  const health = useHealth();

  return (
    <Panel
      title="System status"
      subtitle="Read from the PACTRA API for this view. Unreachable is reported as unreachable, never as healthy."
      actions={<DataTierBadge tier="live" />}
    >
      <ResultBoundary result={health.data} isLoading={health.isPending} what="health" skeletonRows={1}>
        {(data) => (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="secure" icon={<Activity aria-hidden className="size-3.5" />}>
                {data.status.toUpperCase()}
              </Badge>
              <Badge
                tone={data.payment_test_mode ? "secure" : "critical"}
                variant="outline"
                title="Whether the payment provider is pinned to test mode in this process."
              >
                {data.payment_test_mode ? "PAYMENT TEST MODE" : "NOT IN PAYMENT TEST MODE"}
              </Badge>
            </div>

            <KeyValueGrid columns={3}>
              <KeyValue label="Status">
                <span className="num">{data.status}</span>
              </KeyValue>
              <KeyValue label="Environment">
                <span className="num">{data.app_env}</span>
              </KeyValue>
              <KeyValue
                label="Real-money execution"
                hint="The Razorpay adapter is test-mode-only and partial at this baseline."
              >
                <span className="num">NONE</span>
              </KeyValue>
            </KeyValueGrid>
          </div>
        )}
      </ResultBoundary>
    </Panel>
  );
}
