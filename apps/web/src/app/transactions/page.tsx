import type { Metadata } from "next";

import { ALL_ROUTES } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { TransactionsView } from "@/components/transactions/TransactionsView";
import { Badge } from "@/components/ui/Badge";
import { DataTierBadge } from "@/components/ui/DataTier";
import { Panel } from "@/components/ui/Panel";
import { PaymentStateMachineView } from "@/components/viz/PaymentStateMachine";
import { TimeoutAfterCreate } from "@/components/viz/TimeoutAfterCreate";

export const metadata: Metadata = { title: "Transactions" };

export default function TransactionsPage() {
  const blurb = ALL_ROUTES.find((item) => item.href === "/transactions")?.blurb;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Transactions"
        title="Payment integrity"
        description={blurb}
        actions={<Badge tone="secure" variant="outline">RAZORPAY TEST MODE ONLY</Badge>}
      />

      <TransactionsView />

      <Panel
        title="PaymentIntent state machine"
        subtitle="The real transition table. A payment moves only along an edge this table permits — never because a provider said so and never because a message arrived in a particular order."
        actions={<DataTierBadge tier="generated" />}
      >
        <PaymentStateMachineView />
      </Panel>

      <TimeoutAfterCreate />

      <Panel title="Why an HTTP request cannot move money">
        <div className="grid gap-4 lg:grid-cols-3">
          <Explainer
            title="The route writes, it does not call"
            body="Requesting a payment writes a durable PaymentIntent and an outbox row inside one transaction, then returns. The provider is reached only by the outbox worker, out of band. LLM → provider has no path because no code reachable from an HTTP request talks to a payment rail."
          />
          <Explainer
            title="The caller supplies nothing that matters"
            body="There is no field for the amount, the merchant, the product, the currency or a capability set. The intent is derived entirely from the authorization the kernel already holds, so a mutated amount cannot be offered — only refused-that-was-never-asked."
          />
          <Explainer
            title="The idempotency key is the caller's, and required"
            body="It arrives in the Idempotency-Key header and the server will not mint one. Generating it server-side would make every retry a new logical payment, which is the opposite of what the header is for."
          />
        </div>
      </Panel>
    </div>
  );
}

function Explainer({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
      <h3 className="text-[12.5px] font-semibold tracking-tight text-[color:var(--color-ink)]">{title}</h3>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">{body}</p>
    </div>
  );
}
