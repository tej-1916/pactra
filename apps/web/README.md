# PACTRA Console

**PACTRA — Deterministic Transaction Verification for Agentic Commerce.**
AI decides what it wants to do. PACTRA decides what it is allowed to do.

The read-only operations console for the PACTRA verification layer. Next.js 16 ·
React 19 · TypeScript · Tailwind v4 · Vitest.

Project overview and reviewer summary: [`../../README.md`](../../README.md).

## Running it

```bash
npm install
cp .env.example .env          # then edit if your API is not on :8000
npm run dev                   # http://localhost:3000
```

The console needs the PACTRA API for anything live:

```bash
# from the repository root
make migrate                  # once, against your Postgres
uvicorn apps.api.pactra.main:app --reload
```

Without it, every live surface renders **PACTRA API unavailable** — deliberately,
rather than rendering zeroes.

## The three data tiers, and why they are labelled

Every number on this console belongs to exactly one tier, and each is badged
where it appears. Keeping them apart is the point: a repository test count and a
runtime health metric are different claims, and a console that lets one read as
the other is not trustworthy.

| Tier | Source | Badge |
|---|---|---|
| **Live runtime** | The PACTRA API, read for this request | `LIVE RUNTIME` |
| **Generated** | Backend source, exported by `scripts/export_reference.py` | `GENERATED FROM SOURCE` |
| **Development benchmark** | A recorded harness run read from `reports/` | `LAST VERIFIED DEVELOPMENT BENCHMARK` |

Nothing is hardcoded. There is no component containing a literal block rate, run
count, or test count: every such number is read from the API, from the generated
export, or from a recorded report at render time.

### Regenerating the reference export

The protocol support matrix, the three known-limitation registers, the
PaymentIntent transition table and the kernel enums are backend source of truth
with no HTTP surface. They are imported and serialized rather than re-typed —
re-typing them by hand is exactly the drift `services/adapters/support.py` exists
to prevent.

```bash
npm run export-reference      # writes src/data/*.generated.json
```

Run it after any change to the support matrix, the limitation registers, the
payment state machine, or the shared enums.

The generated files **are tracked in git**. That is deliberate: it is what lets a
fresh clone typecheck, test and build the console without a Python environment,
and the fresh-clone reproduction is part of the release evidence. Reports under
`reports/` stay gitignored, because a recorded benchmark is a measurement of one
machine at one moment and must not ship as if it were current.

### Producing a benchmark

The Attack Lab and the risk-evaluation harness are CLI-only by design (AL-06: an
ingress route would be an unauthenticated front door, and PACTRA has no auth
layer to gate one). The console displays a recorded run and says so.

```bash
# from the repository root
python -m services.attack_lab.run --all --iterations 10 --require-postgres \
  --out reports/attack-lab/run.json
python -m services.risk_engine.run --evaluate --iterations 10 \
  --out reports/risk-engine/run.json
```

Reports are gitignored on purpose, so a fresh clone shows **RUNNER NOT
CONNECTED**. That is the honest state, not a bug.

## Architecture

```text
browser  ──►  /api/pactra/*  (Route Handlers, server-side)  ──►  PACTRA API
                    │
                    └── reads reports/*.json from disk (benchmark tier)
```

`PACTRA_API_URL` and `PACTRA_REPORTS_DIR` are read in `server-only` modules and
never reach the client bundle. There is no `NEXT_PUBLIC_` variable and there
should never be one: a value that reaches the browser is public.

```text
src/
├── app/                  10 page routes + the /api/pactra proxy
├── components/
│   ├── ui/               design-system primitives (badges, panels, states)
│   ├── shell/            sidebar, brand, live API status
│   ├── viz/              kernel boundary, payment state machine, timeout story
│   └── <domain>/         command, mission, attack, audit, risk, adapters, system
├── lib/
│   ├── api/              typed client, server fetch, report loader
│   ├── types/            transcribed backend response contracts
│   ├── semantics.ts      status → visual treatment (the colour-semantics rules)
│   ├── reason-codes.ts   plain-language text shown BESIDE a code, never instead
│   └── redaction.ts      last-line defence over open-ended payload maps
└── data/                 *.generated.json — do not edit by hand
```

## Colour semantics

One rule matters more than the rest:

> **A blocked attack is a SUCCESS for PACTRA and is never rendered red.**

Severity and result are different axes. `SEVERITY: CRITICAL` describes how bad an
attack would be; `RESULT: BLOCKED` describes what the system did about it.
Severity renders **outlined**, results render **solid**, so the two never read as
one. `ERROR` is never presented as `BLOCKED` — an exception proves nothing.

## Quality gates

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

All four pass on the submission release, along with a fresh-clone reproduction.
Two non-blocking Turbopack filesystem-tracing warnings remain in the production
build; they are reported rather than suppressed. The consolidated verification
record is in [`../../docs/evidence.md`](../../docs/evidence.md).

## What the console will not do

* Execute attacks, or simulate executing them.
* Mutate an audit event to demonstrate that tampering is detected.
* Invent a backend endpoint. Where one is missing the UI says so in place —
  grep the source for `FRONTEND_BACKEND_GAP`.
* Present a browser-local mission list as a system inventory.
* Render an unreachable backend as zero.
