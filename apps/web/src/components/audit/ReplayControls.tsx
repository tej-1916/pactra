import {
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  Info,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
} from "lucide-react";

export interface ReplayControlsProps {
  currentIndex: number;
  totalEvents: number;
  onPrev: () => void;
  onNext: () => void;
  onReset: () => void;
  isDemo: boolean;
  runtimeVerification?: {
    auditValid: boolean;
    trusted: boolean;
    eventsReplayed: number;
    reasonCode: string;
  } | null;
  provenance: {
    origin: string;
    trustClassification: string;
    authorityPath: string;
  };
}

export function ReplayControls({
  currentIndex,
  totalEvents,
  onPrev,
  onNext,
  onReset,
  isDemo,
  runtimeVerification,
  provenance,
}: ReplayControlsProps) {
  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-4 space-y-4 min-w-0 max-w-full">
      {/* Replay Controls Scrubber Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--pactra-line)] pb-3">
        <div className="flex items-center gap-2 font-mono">
          <span className="text-[12px] font-bold text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-surface-2)] border border-[color:var(--pactra-indigo)]/40 px-3 py-1 rounded">
            CURSOR: EVENT {totalEvents > 0 ? currentIndex + 1 : 0} OF {totalEvents}
          </span>
          <span className="text-[11px] text-[color:var(--pactra-ink-muted)]">
            (UI navigation state — not transaction state)
          </span>
        </div>

        {/* Stepper Buttons */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPrev}
            disabled={currentIndex <= 0}
            className="rounded border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] px-3 py-1.5 font-mono text-[11px] font-semibold text-[color:var(--pactra-ink)] hover:bg-[color:var(--pactra-surface-3)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1 cursor-pointer"
          >
            <ChevronLeft className="size-3.5" />
            Previous Event
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={currentIndex >= totalEvents - 1}
            className="rounded border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] px-3 py-1.5 font-mono text-[11px] font-semibold text-[color:var(--pactra-ink)] hover:bg-[color:var(--pactra-surface-3)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1 cursor-pointer"
          >
            Next Event
            <ChevronRight className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={onReset}
            className="rounded border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] px-2.5 py-1.5 font-mono text-[11px] text-[color:var(--pactra-ink-muted)] hover:text-[color:var(--pactra-ink)] hover:bg-[color:var(--pactra-surface-3)] transition-colors cursor-pointer"
            title="Reset cursor to first event"
          >
            <RotateCcw className="size-3.5" />
          </button>
        </div>
      </div>

      {/* Replay Reconstruction Notice (Mandatory disclosure) */}
      <div className="rounded border border-[color:var(--pactra-indigo)]/30 bg-[color:var(--pactra-surface-2)] p-3 space-y-1">
        <div className="flex items-center gap-1.5 font-mono text-[11px] font-bold text-[color:var(--pactra-indigo)]">
          <Info className="size-3.5 text-[color:var(--pactra-indigo)] shrink-0" />
          REPLAY EVIDENCE RECONSTRUCTION NOTICE
        </div>
        <p className="text-[12px] text-[color:var(--pactra-ink-secondary)] leading-relaxed">
          Replay is evidence reconstruction from recorded audit evidence, not payment re-execution. Replaying does not execute charges, rerun AI models, or contact payment providers.
        </p>
      </div>

      {/* Verification State Box */}
      <div className="rounded bg-[color:var(--pactra-surface-2)] p-3 space-y-2 font-mono text-[11px] min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--pactra-line)] pb-1.5">
          <span className="text-[10.5px] font-bold text-[color:var(--pactra-ink)] uppercase tracking-wider">
            REPLAY VERIFICATION STATUS
          </span>
          <div>
            {isDemo ? (
              <span className="text-[10px] font-semibold text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/15 px-2 py-0.5 rounded border border-[color:var(--pactra-indigo)]/30">
                DEMO CONSISTENCY EXAMPLE
              </span>
            ) : runtimeVerification ? (
              runtimeVerification.auditValid ? (
                <span className="text-[10px] font-semibold text-[color:var(--pactra-success)] bg-[color:var(--pactra-success)]/15 px-2 py-0.5 rounded inline-flex items-center gap-1 border border-[color:var(--pactra-success)]/30">
                  <CheckCircle2 className="size-3" />
                  AUDIT VALID ({runtimeVerification.reasonCode})
                </span>
              ) : (
                <span className="text-[10px] font-semibold text-[color:var(--pactra-critical)] bg-[color:var(--pactra-critical)]/15 px-2 py-0.5 rounded inline-flex items-center gap-1 border border-[color:var(--pactra-critical)]/30">
                  <AlertTriangle className="size-3" />
                  AUDIT VERIFICATION FAILED ({runtimeVerification.reasonCode})
                </span>
              )
            ) : (
              <span className="text-[10px] text-[color:var(--pactra-ink-muted)] bg-[color:var(--pactra-surface-3)] px-2 py-0.5 rounded inline-flex items-center gap-1">
                <HelpCircle className="size-3" />
                VERIFICATION NOT AVAILABLE
              </span>
            )}
          </div>
        </div>

        {/* Machine Verification Details if Runtime Evidence Loaded */}
        {!isDemo && runtimeVerification && (
          <div className="grid gap-2 sm:grid-cols-3 text-[10.5px] pt-1">
            <div>
              <span className="text-[color:var(--pactra-ink-muted)]">audit_valid: </span>
              <span className={runtimeVerification.auditValid ? "text-[color:var(--pactra-success)] font-bold" : "text-[color:var(--pactra-critical)] font-bold"}>
                {runtimeVerification.auditValid ? "TRUE" : "FALSE"}
              </span>
            </div>
            <div>
              <span className="text-[color:var(--pactra-ink-muted)]">trusted: </span>
              <span className={runtimeVerification.trusted ? "text-[color:var(--pactra-success)] font-bold" : "text-[color:var(--pactra-warning)] font-bold"}>
                {runtimeVerification.trusted ? "TRUE (REPLAYABLE)" : "FALSE"}
              </span>
            </div>
            <div>
              <span className="text-[color:var(--pactra-ink-muted)]">events_replayed: </span>
              <span className="text-[color:var(--pactra-ink)] font-bold">{runtimeVerification.eventsReplayed}</span>
            </div>
          </div>
        )}
      </div>

      {/* Provenance Classification */}
      <div className="grid gap-3 sm:grid-cols-3 font-mono text-[11px]">
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">INPUT ORIGIN</div>
          <div className="text-[color:var(--pactra-ink)] font-semibold">{provenance.origin}</div>
        </div>

        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">TRUST CLASSIFICATION</div>
          <div className="text-[color:var(--pactra-indigo)] font-semibold">{provenance.trustClassification}</div>
        </div>

        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">AUTHORITY PATH</div>
          <div className="text-[color:var(--pactra-success)] font-semibold">{provenance.authorityPath}</div>
        </div>
      </div>
    </div>
  );
}
