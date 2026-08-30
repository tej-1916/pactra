import "server-only";

import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

import type { AttackRunReport, ReportEnvelope, RiskEvalReport } from "@/lib/types/benchmark";

/**
 * Reads the GENERATED evaluation artifacts off disk.
 *
 * These files are the only honest source for attack-lab and risk-evaluation
 * numbers, because neither harness has an HTTP surface (AL-06: translation and
 * evaluation are reachable from the CLI and from nowhere else, deliberately).
 *
 * Three rules this module enforces:
 *
 * 1. **Nothing is fabricated when a file is missing.** The absence of a report
 *    returns `NO_REPORT_FOUND`, which the UI renders as RUNNER NOT CONNECTED.
 *    Returning an empty report would put "0 attacks blocked" on screen, which
 *    is a measurement nobody made.
 * 2. **The newest run wins, and says which file it came from.** A console
 *    showing a benchmark must be able to answer "which run is this".
 * 3. **Reports are never written.** This module opens files read-only. The
 *    console cannot cause a benchmark to exist.
 *
 * The build prints a file-tracing advisory for the reads below, because the
 * reports directory is operator-configurable and therefore cannot be statically
 * scoped. That is accepted: making the path a compile-time constant would take
 * `PACTRA_REPORTS_DIR` away from the operator to quiet a warning about
 * deployment bundle size, which this console does not have.
 */

function reportsRoot(): string {
  const configured = process.env.PACTRA_REPORTS_DIR ?? "reports";
  if (path.isAbsolute(configured)) return configured;
  // `process.cwd()` is apps/web under `next dev`/`next start`; the reports live
  // at the repository root, two levels up.
  return path.resolve(process.cwd(), "..", "..", configured);
}

async function newestJsonIn(dir: string): Promise<string | null> {
  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch {
    return null;
  }
  const candidates = entries.filter((name) => name.endsWith(".json"));
  if (candidates.length === 0) return null;

  const stamped = await Promise.all(
    candidates.map(async (name) => {
      const full = path.join(dir, name);
      try {
        const info = await stat(full);
        return { full, mtime: info.mtimeMs };
      } catch {
        return { full, mtime: 0 };
      }
    }),
  );
  stamped.sort((a, b) => b.mtime - a.mtime);
  return stamped[0]?.full ?? null;
}

async function loadNewest<T>(subdir: string, produce: string): Promise<ReportEnvelope<T>> {
  const dir = path.join(reportsRoot(), subdir);
  const file = await newestJsonIn(dir);
  if (file === null) {
    return {
      available: false,
      reason: "NO_REPORT_FOUND",
      detail: `No evaluation report found in ${path.relative(process.cwd(), dir)}. Produce one with: ${produce}`,
    };
  }
  try {
    const raw = await readFile(file, "utf8");
    return {
      available: true,
      report: JSON.parse(raw) as T,
      sourceFile: path.basename(file),
      loadedAt: new Date().toISOString(),
    };
  } catch (error) {
    return {
      available: false,
      reason: "REPORT_UNREADABLE",
      detail: `${path.basename(file)} could not be parsed: ${
        error instanceof Error ? error.message : "unknown error"
      }`,
    };
  }
}

export function loadAttackReport(): Promise<ReportEnvelope<AttackRunReport>> {
  return loadNewest<AttackRunReport>(
    "attack-lab",
    "python -m services.attack_lab.run --all --iterations 10 --require-postgres --out reports/attack-lab/run.json",
  );
}

export function loadRiskEvaluation(): Promise<ReportEnvelope<RiskEvalReport>> {
  return loadNewest<RiskEvalReport>(
    "risk-engine",
    "python -m services.risk_engine.run --evaluate --iterations 10 --out reports/risk-engine/run.json",
  );
}
