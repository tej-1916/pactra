import { ArrowRight, ShieldAlert } from "lucide-react";

import { KernelPipeline } from "@/components/viz/KernelPipeline";

/**
 * The fifteen-second statement.
 *
 * Everything above the fold says one thing: the reasoning layer is outside the
 * boundary. The lines here are the project's own, not marketing written for the
 * console — they appear verbatim in the README and the build spec.
 */
export function PostureBanner() {
  return (
    <section className="panel relative overflow-hidden bg-[color:var(--color-surface)] p-5 sm:p-6">
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(680px_240px_at_15%_-30%,color-mix(in_srgb,var(--color-accent)_10%,transparent),transparent_70%)]"
      />
      <div className="relative flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="label-xs mb-2 text-[color:var(--color-accent)]">
              Adversarial Transaction Security for Agentic Commerce
            </p>
            <h1 className="text-[26px] leading-[1.15] font-semibold tracking-tight text-[color:var(--color-ink)] sm:text-[30px]">
              AI proposes.
              <br />
              <span className="text-[color:var(--color-secure)]">
                PACTRA decides what can move money.
              </span>
            </h1>
            <p className="mt-3 max-w-[62ch] text-[13px] leading-relaxed text-[color:var(--color-ink-2)]">
              Probabilistic reasoning. Deterministic transaction authority. The model, the agent and
              every merchant sit outside the security boundary — transaction invariants hold even
              when all three are compromised.
            </p>
          </div>

          <div className="flex items-center gap-2 rounded-lg border border-[color:var(--color-critical)]/30 bg-[color:var(--color-critical)]/[0.05] px-3 py-2.5">
            <ShieldAlert aria-hidden className="size-4 shrink-0 text-[color:var(--color-critical)]" />
            <p className="text-[11.5px] leading-snug font-semibold text-[color:var(--color-critical)]">
              AI IS NOT THE
              <br />
              SECURITY BOUNDARY
            </p>
          </div>
        </div>

        <KernelPipeline />

        <p className="flex flex-wrap items-center gap-2 border-t border-[color:var(--color-line)] pt-3 text-[11.5px] text-[color:var(--color-ink-4)]">
          <span className="num">AI Agent</span>
          <ArrowRight aria-hidden className="size-3" />
          <span className="num text-[color:var(--color-secure)]">PACTRA Kernel</span>
          <ArrowRight aria-hidden className="size-3" />
          <span className="num">Authorized Payment</span>
          <span className="ml-1">— and never a path that skips the middle term.</span>
        </p>
      </div>
    </section>
  );
}
