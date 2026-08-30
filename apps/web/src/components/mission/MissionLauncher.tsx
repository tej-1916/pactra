"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, Play } from "lucide-react";

import { Panel } from "@/components/ui/Panel";
import { ErrorState, UnavailableState } from "@/components/ui/States";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { api, type CreateMissionBody } from "@/lib/api/client";
import { newIdempotencyKey, useMissionRegister } from "@/lib/hooks/useMissionRegister";

/**
 * Runs a real mission through the real kernel.
 *
 * The form collects only what `MissionConstraints` accepts. That schema is
 * `extra="forbid"`, so a field this console invented would be rejected by the
 * backend rather than absorbed — which is the correct relationship: the console
 * does not get to author any part of a user policy.
 *
 * The default query is the one the README documents, and it is chosen because
 * its best valid offer (₹4,299) sits above the soft budget and below the hard
 * ceiling — so the mission lands in AWAITING_APPROVAL and the human-approval
 * boundary is actually exercised instead of being described.
 */

const DEFAULTS = {
  rawQuery: "Find wireless earbuds under 4000, min rating 4.2",
  category: "wireless_earbuds",
  softBudget: 4000,
  hardLimit: 4500,
  minRating: 4.2,
  quantity: 1,
};

type Submission =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "failed"; status: number; reasonCode: string | null; detail: string }
  | { kind: "unavailable"; detail: string };

export function MissionLauncher() {
  const router = useRouter();
  const { register } = useMissionRegister();
  const [form, setForm] = useState(DEFAULTS);
  const [submission, setSubmission] = useState<Submission>({ kind: "idle" });

  const invalidBudgets = form.softBudget > form.hardLimit;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (invalidBudgets) return;
    setSubmission({ kind: "running" });

    const body: CreateMissionBody = {
      raw_query: form.rawQuery.trim().length > 0 ? form.rawQuery.trim() : null,
      quantity: form.quantity,
      constraints: {
        category: form.category,
        soft_budget_inr: form.softBudget,
        hard_limit_inr: form.hardLimit,
        min_rating: form.minRating,
        currency: "INR",
      },
    };

    const result = await api.createMission(body);
    if (result.kind === "ok") {
      register({
        id: result.data.id,
        rawQuery: result.data.raw_query,
        createdAt: result.data.created_at,
        idempotencyKey: newIdempotencyKey(result.data.id),
      });
      router.push(`/missions/${result.data.id}`);
      return;
    }
    if (result.kind === "unavailable") {
      setSubmission({ kind: "unavailable", detail: result.detail });
      return;
    }
    setSubmission({
      kind: "failed",
      status: result.status,
      reasonCode: result.reasonCode,
      detail: result.detail,
    });
  }

  const running = submission.kind === "running";

  return (
    <Panel
      title="Run a mission"
      subtitle="Executes the real kernel path: discovery against the mock merchant transport, normalization, provenance and taint, deterministic policy, transaction binding. Nothing here is simulated in the console."
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="User intent (raw query)" hint="Free text. It is stored as-is and never becomes a security input.">
          <input
            type="text"
            value={form.rawQuery}
            maxLength={2000}
            onChange={(event) => setForm({ ...form, rawQuery: event.target.value })}
            className="w-full rounded border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-2)] px-3 py-2 text-[13px] text-[color:var(--color-ink)] placeholder:text-[color:var(--color-ink-4)]"
            placeholder="Find wireless earbuds under 4000, min rating 4.2"
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Field label="Category">
            <input
              type="text"
              value={form.category}
              onChange={(event) => setForm({ ...form, category: event.target.value })}
              className={inputClass}
            />
          </Field>
          <Field label="Soft budget (₹)" hint="Above this, a human must approve. It does not permit anything on its own.">
            <input
              type="number"
              min={1}
              value={form.softBudget}
              onChange={(event) => setForm({ ...form, softBudget: Number(event.target.value) })}
              className={inputClass}
            />
          </Field>
          <Field label="Hard limit (₹)" hint="The absolute ceiling. No approval can raise it.">
            <input
              type="number"
              min={1}
              value={form.hardLimit}
              onChange={(event) => setForm({ ...form, hardLimit: Number(event.target.value) })}
              className={inputClass}
            />
          </Field>
          <Field label="Minimum rating">
            <input
              type="number"
              min={0}
              max={5}
              step={0.1}
              value={form.minRating}
              onChange={(event) => setForm({ ...form, minRating: Number(event.target.value) })}
              className={inputClass}
            />
          </Field>
        </div>

        {invalidBudgets ? (
          <p className="text-[12px] text-[color:var(--color-critical)]">
            The soft budget cannot exceed the hard limit. `MissionConstraints` rejects this
            ordering, so the request is not sent.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={running || invalidBudgets}
            className="inline-flex items-center gap-2 rounded border border-[color:var(--color-accent)]/45 bg-[color:var(--color-accent)]/12 px-3.5 py-2 text-[12.5px] font-semibold text-[color:var(--color-accent)] transition-colors hover:bg-[color:var(--color-accent)]/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <Play aria-hidden className="size-4" />
            )}
            {running ? "Running through the kernel…" : "Run mission"}
          </button>
          <p className="text-[11.5px] text-[color:var(--color-ink-4)]">
            Creates real rows and a real audit chain. It authorizes nothing and moves no money.
          </p>
        </div>

        {submission.kind === "unavailable" ? (
          <UnavailableState title="PACTRA API unavailable" detail={submission.detail} />
        ) : null}
        {submission.kind === "failed" ? (
          <ErrorState
            title={`The API refused this request (HTTP ${submission.status})`}
            detail={
              <div className="space-y-2">
                <ReasonCode code={submission.reasonCode} describe />
                <p>{submission.detail}</p>
              </div>
            }
          />
        ) : null}
      </form>
    </Panel>
  );
}

const inputClass =
  "w-full rounded border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-2)] px-3 py-2 text-[13px] num text-[color:var(--color-ink)]";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="label-xs mb-1.5 block text-[color:var(--color-ink-4)]" title={hint}>
        {label}
      </span>
      {children}
    </label>
  );
}
