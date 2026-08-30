import { Bot, Building2, CheckCircle2, CreditCard, FileClock, User } from "lucide-react";

import { cn } from "@/lib/format";

/**
 * The thesis, drawn.
 *
 * The whole point of this component is the ENCLOSURE: untrusted things enter
 * from the left, a bounded kernel sits in the middle, and a payment leaves only
 * from the right. Nothing crosses the box. If a reader takes one thing from
 * this console it should be that the AI is outside the boundary, and that is a
 * spatial claim, not a caption.
 *
 * The stage list is the real Phase 2–7 order and is not decorative.
 */

const KERNEL_STAGES = [
  { name: "Provenance", note: "Where every value came from travels with the value." },
  { name: "Taint", note: "Untrusted stays untrusted through every transformation." },
  { name: "Authority", note: "Lower-authority data cannot write higher-authority state." },
  { name: "Capability", note: "A principal holds only what the server-owned registry grants." },
  { name: "Policy", note: "Deterministic rules. Never a prompt." },
  { name: "Binding", note: "An approval commits to ONE exact transaction." },
  { name: "Authorization", note: "One-time, expiring, consumed atomically." },
  { name: "Risk — advisory", note: "Advice. It decides nothing." },
  { name: "Replay protection", note: "A consumed authorization cannot authorize again." },
];

export function KernelPipeline({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3 xl:flex-row xl:items-stretch", className)}>
      {/* ---- untrusted side ------------------------------------------------ */}
      <div className="flex flex-row gap-2 xl:w-[190px] xl:flex-col">
        <Node
          icon={<User aria-hidden className="size-3.5" />}
          title="USER INTENT"
          caption="Natural language"
          tone="neutral"
        />
        <Node
          icon={<Bot aria-hidden className="size-3.5" />}
          title="AI / AGENT"
          caption="Proposes only"
          tone="taint"
        />
        <Node
          icon={<Building2 aria-hidden className="size-3.5" />}
          title="MERCHANT INPUT"
          caption="Untrusted"
          tone="taint"
        />
      </div>

      <Connector />

      {/* ---- the boundary --------------------------------------------------- */}
      <div className="relative flex-1 overflow-hidden rounded-lg border border-[color:var(--color-secure)]/35 bg-[color:var(--color-secure)]/[0.035] p-3.5">
        <span
          aria-hidden
          className="absolute inset-x-0 top-0 h-[2px] bg-[linear-gradient(90deg,transparent,var(--color-secure),transparent)] bg-[length:200%_100%] [animation:pactra-flow_5s_linear_infinite]"
        />
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="label-xs text-[color:var(--color-secure)]">PACTRA SECURITY KERNEL</p>
          <p className="text-[11px] font-semibold text-[color:var(--color-ink-3)]">
            Deterministic · the security boundary
          </p>
        </div>
        <ol className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {KERNEL_STAGES.map((stage, index) => (
            <li
              key={stage.name}
              title={stage.note}
              className="flex min-w-0 items-center gap-2 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-2 py-1.5"
            >
              <span className="num text-[10px] text-[color:var(--color-ink-4)]">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="truncate text-[11.5px] font-medium text-[color:var(--color-ink-2)]">
                {stage.name}
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-3 border-t border-[color:var(--color-line)] pt-2.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
          Every stage is deterministic Python. The reasoning layer feeds proposals into the top and
          holds no path through the boundary — there is no code reachable from a model, an agent, or
          an HTTP request that talks to a payment rail.
        </p>
      </div>

      <Connector />

      {/* ---- authorized side ------------------------------------------------ */}
      <div className="flex flex-row gap-2 xl:w-[190px] xl:flex-col">
        <Node
          icon={<CheckCircle2 aria-hidden className="size-3.5" />}
          title="AUTHORIZATION"
          caption="One-time, bound"
          tone="secure"
        />
        <Node
          icon={<CreditCard aria-hidden className="size-3.5" />}
          title="PAYMENT EXECUTOR"
          caption="Outbox · Razorpay TEST"
          tone="secure"
        />
        <Node
          icon={<FileClock aria-hidden className="size-3.5" />}
          title="TAMPER-EVIDENT AUDIT"
          caption="Hash chain · replay"
          tone="secure"
        />
      </div>
    </div>
  );
}

function Connector() {
  return (
    <div
      aria-hidden
      className="hidden shrink-0 items-center justify-center xl:flex xl:w-6"
    >
      <span className="h-[1px] w-full bg-[linear-gradient(90deg,transparent,var(--color-line-strong),transparent)]" />
    </div>
  );
}

function Node({
  icon,
  title,
  caption,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  caption: string;
  tone: "taint" | "secure" | "neutral";
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 flex-col gap-1 rounded-lg border px-2.5 py-2",
        tone === "taint" &&
          "border-[color:var(--color-taint)]/30 bg-[color:var(--color-taint)]/[0.05]",
        tone === "secure" &&
          "border-[color:var(--color-secure)]/25 bg-[color:var(--color-secure)]/[0.04]",
        tone === "neutral" && "border-[color:var(--color-line)] bg-[color:var(--color-surface-2)]",
      )}
    >
      <span
        className={cn(
          "flex items-center gap-1.5 text-[10px] font-semibold tracking-[0.07em]",
          tone === "taint" && "text-[color:var(--color-taint)]",
          tone === "secure" && "text-[color:var(--color-secure)]",
          tone === "neutral" && "text-[color:var(--color-ink-2)]",
        )}
      >
        {icon}
        <span className="truncate">{title}</span>
      </span>
      <span className="truncate text-[10.5px] text-[color:var(--color-ink-4)]">{caption}</span>
    </div>
  );
}
