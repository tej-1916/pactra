import Link from "next/link";
import { ArrowRight, Store, Crosshair, FileClock, Activity } from "lucide-react";
import { Panel } from "@/components/ui/Panel";

export function NextActionsSection() {
  const actions = [
    {
      title: "Explore Live Commerce",
      href: "/commerce",
      icon: Store,
      desc: "Follow an end-to-end AI purchase through admission, binding, user authorization, and execution.",
      tag: "COMMERCE WORKBENCH",
    },
    {
      title: "Open Attack Lab",
      href: "/attack-lab",
      icon: Crosshair,
      desc: "Simulate prompt injection and contract mutation attacks against the deterministic enforcement boundary.",
      tag: "ADVERSARIAL SUITE",
    },
    {
      title: "Inspect Audit Trail",
      href: "/audit",
      icon: FileClock,
      desc: "Verify deterministic evidence, hash chain integrity, and replay historical Decision Trace events.",
      tag: "AUDIT & REPLAY",
    },
    {
      title: "View System Contract",
      href: "/system",
      icon: Activity,
      desc: "Examine published contract boundaries, eleven invariants, and adapter translation rules.",
      tag: "CONTRACT SPEC",
    },
  ];

  return (
    <Panel
      title="JUDGE & RECRUITER VERIFICATION PATH"
      subtitle="Select a surface to inspect the live transaction workbench, adversarial tests, or audit trail."
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {actions.map((act) => {
          const Icon = act.icon;
          return (
            <Link
              key={act.href}
              href={act.href}
              className="group rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between hover:border-[color:var(--pactra-indigo)] hover:bg-[color:var(--pactra-surface-3)] transition-all duration-150"
            >
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Icon className="size-4 text-[color:var(--pactra-indigo)] group-hover:scale-110 transition-transform" />
                  <span className="font-mono text-[9.5px] font-bold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider">
                    {act.tag}
                  </span>
                </div>
                <h3 className="font-display text-[14px] font-bold text-[color:var(--pactra-ink)] group-hover:text-[color:var(--pactra-indigo)]">
                  {act.title}
                </h3>
                <p className="text-[12px] leading-snug text-[color:var(--pactra-ink-secondary)]">
                  {act.desc}
                </p>
              </div>

              <div className="mt-4 pt-2 flex items-center gap-1 font-mono text-[11px] font-bold text-[color:var(--pactra-indigo)]">
                <span>Explore</span>
                <ArrowRight className="size-3.5 group-hover:translate-x-1 transition-transform" />
              </div>
            </Link>
          );
        })}
      </div>
    </Panel>
  );
}
