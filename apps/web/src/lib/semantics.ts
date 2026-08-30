/**
 * The mapping from backend vocabulary to visual treatment.
 *
 * This module exists so the mapping is decided ONCE and is testable. The rule it
 * encodes, which is easy to get wrong and expensive to get wrong:
 *
 *   **A blocked attack is a SUCCESS for PACTRA and is never rendered red.**
 *
 * Severity and result are different axes. `SEVERITY: CRITICAL` describes how bad
 * the attack would be; `RESULT: BLOCKED` describes what the system did about it.
 * A screen that paints both red tells a reader the system failed. So severity is
 * rendered OUTLINED and result is rendered SOLID, and `severityTone` is
 * deliberately never used to colour a result.
 */

export type Tone = "secure" | "advisory" | "critical" | "taint" | "neutral" | "accent";

export interface ToneClasses {
  /** Solid treatment. For a RESULT. */
  solid: string;
  /** Outlined treatment. For a SEVERITY or a classification. */
  outline: string;
  /** Bare foreground colour, for icons and inline text. */
  text: string;
  /** A 1px rule or bar in the tone. */
  rule: string;
}

export const TONES: Record<Tone, ToneClasses> = {
  secure: {
    solid: "bg-[color:var(--color-secure)]/12 text-[color:var(--color-secure)] border-[color:var(--color-secure)]/35",
    outline: "bg-transparent text-[color:var(--color-secure)] border-[color:var(--color-secure)]/45",
    text: "text-[color:var(--color-secure)]",
    rule: "bg-[color:var(--color-secure)]",
  },
  advisory: {
    solid: "bg-[color:var(--color-advisory)]/12 text-[color:var(--color-advisory)] border-[color:var(--color-advisory)]/35",
    outline: "bg-transparent text-[color:var(--color-advisory)] border-[color:var(--color-advisory)]/45",
    text: "text-[color:var(--color-advisory)]",
    rule: "bg-[color:var(--color-advisory)]",
  },
  critical: {
    solid: "bg-[color:var(--color-critical)]/12 text-[color:var(--color-critical)] border-[color:var(--color-critical)]/35",
    outline: "bg-transparent text-[color:var(--color-critical)] border-[color:var(--color-critical)]/45",
    text: "text-[color:var(--color-critical)]",
    rule: "bg-[color:var(--color-critical)]",
  },
  taint: {
    solid: "bg-[color:var(--color-taint)]/12 text-[color:var(--color-taint)] border-[color:var(--color-taint)]/35",
    outline: "bg-transparent text-[color:var(--color-taint)] border-[color:var(--color-taint)]/45",
    text: "text-[color:var(--color-taint)]",
    rule: "bg-[color:var(--color-taint)]",
  },
  accent: {
    solid: "bg-[color:var(--color-accent)]/12 text-[color:var(--color-accent)] border-[color:var(--color-accent)]/35",
    outline: "bg-transparent text-[color:var(--color-accent)] border-[color:var(--color-accent)]/45",
    text: "text-[color:var(--color-accent)]",
    rule: "bg-[color:var(--color-accent)]",
  },
  neutral: {
    solid: "bg-[color:var(--color-surface-3)] text-[color:var(--color-ink-2)] border-[color:var(--color-line-strong)]",
    outline: "bg-transparent text-[color:var(--color-ink-2)] border-[color:var(--color-line-strong)]",
    text: "text-[color:var(--color-ink-2)]",
    rule: "bg-[color:var(--color-line-strong)]",
  },
};

// --------------------------------------------------------------------------- //
// Attack lab
// --------------------------------------------------------------------------- //

export type AttackStatusValue = "BLOCKED" | "NOT_BLOCKED" | "ERROR" | "INCONCLUSIVE";

export interface AttackVerdict {
  /** What to print. Never abbreviated into the wrong claim. */
  label: string;
  tone: Tone;
  /** Whether this run produced a security verdict at all. */
  decisive: boolean;
  /** One line explaining what the status means for THIS scenario's direction. */
  meaning: string;
}

/**
 * Interpret one run.
 *
 * `expectedStatus` is required, and that is the point: BLOCKED is the pass for a
 * hostile scenario and a FALSE POSITIVE for a benign control. Reading the status
 * without the declared expectation gets the second case exactly backwards.
 *
 * ERROR is never presented as BLOCKED. An exception proves nothing either way,
 * and laundering a crash into a security success is the specific failure the
 * backend's `AttackStatus.ERROR` exists to prevent.
 */
export function attackVerdict(
  status: AttackStatusValue,
  expectedStatus: AttackStatusValue,
  category: string,
): AttackVerdict {
  if (category === "KNOWN_LIMITATION") {
    return {
      label: "KNOWN LIMITATION",
      tone: "advisory",
      decisive: false,
      meaning:
        "A documented boundary of the security contract, demonstrated rather than hidden. Not a finding and not a blocked attack.",
    };
  }

  switch (status) {
    case "BLOCKED":
      return expectedStatus === "BLOCKED"
        ? {
            label: "BLOCKED",
            tone: "secure",
            decisive: true,
            meaning: "The hostile action was refused by a control, with observed effects to prove it.",
          }
        : {
            label: "FALSE POSITIVE",
            tone: "critical",
            decisive: true,
            meaning: "A benign control was refused. For a control, being blocked is the failure.",
          };
    case "NOT_BLOCKED":
      return expectedStatus === "NOT_BLOCKED"
        ? {
            label: "ALLOWED · CONTROL",
            tone: "secure",
            decisive: true,
            meaning: "A benign request went through, as it must. This is what makes a false-positive rate measurable.",
          }
        : {
            label: "NOT BLOCKED",
            tone: "critical",
            decisive: true,
            meaning: "The hostile action went through. This is a bypass.",
          };
    case "ERROR":
      return {
        label: "ERROR",
        tone: "critical",
        decisive: false,
        meaning:
          "Something unexpected raised while attacking. An exception is not a block — this run proves nothing either way.",
      };
    case "INCONCLUSIVE":
      return {
        label: "INCONCLUSIVE",
        tone: "neutral",
        decisive: false,
        meaning:
          "Preconditions could not be established, so the attack never ran. Excluded from every rate's denominator, never counted on the safe side.",
      };
  }
}

/** Severity is an ordinal scale, and it is NOT CVSS. Rendered outlined, always. */
export function severityTone(severity: string): Tone {
  switch (severity) {
    case "CRITICAL":
    case "HIGH":
      return "critical";
    case "MEDIUM":
      return "advisory";
    default:
      return "neutral";
  }
}

// --------------------------------------------------------------------------- //
// Payment
// --------------------------------------------------------------------------- //

export function paymentStateTone(state: string): Tone {
  switch (state) {
    case "SUCCEEDED":
      return "secure";
    case "PROVIDER_PENDING":
    case "FAILED_RETRYABLE":
      return "advisory";
    case "FAILED_TERMINAL":
      return "critical";
    case "CANCELLED":
      return "neutral";
    default:
      return "accent";
  }
}

export const PAYMENT_STATE_MEANING: Readonly<Record<string, string>> = {
  CREATED: "A durable intent exists. No provider has been contacted.",
  QUEUED: "Handed to the transactional outbox. The worker will pick it up out of band.",
  PROCESSING: "The worker is making a provider call.",
  PROVIDER_PENDING:
    "UNCERTAIN. A provider payment may exist and its outcome is unknown. The only way out is reconciliation — never an optimistic guess.",
  SUCCEEDED: "Settled. Terminal: no further transition is permitted, so a late webhook cannot regress it.",
  FAILED_RETRYABLE: "Failed in a way a retry may resolve. Reachable only once the provider positively reported holding no payment.",
  FAILED_TERMINAL: "Failed permanently. Terminal and absorbing.",
  CANCELLED: "Abandoned before settlement. Terminal.",
};

// --------------------------------------------------------------------------- //
// Mission
// --------------------------------------------------------------------------- //

export function missionStateTone(state: string): Tone {
  switch (state) {
    case "PAYMENT_SUCCEEDED":
    case "COMPLETED":
    case "AUTHORIZED":
      return "secure";
    case "AWAITING_APPROVAL":
      return "advisory";
    case "PAYMENT_FAILED":
      return "critical";
    case "CANCELLED":
      return "neutral";
    default:
      return "accent";
  }
}

export function policyOutcomeTone(decision: string): Tone {
  switch (decision) {
    case "ALLOW":
      return "secure";
    case "REQUIRE_APPROVAL":
      return "advisory";
    case "DENY":
      return "critical";
    default:
      return "neutral";
  }
}

export function authorizationStatusTone(status: string): Tone {
  switch (status) {
    case "ACTIVE":
      return "secure";
    case "PENDING":
      return "advisory";
    case "CONSUMED":
      return "neutral";
    case "EXPIRED":
    case "REVOKED":
      return "critical";
    default:
      return "neutral";
  }
}

// --------------------------------------------------------------------------- //
// Risk — advisory, and the tones say so
// --------------------------------------------------------------------------- //

/**
 * A risk band is advice. CRITICAL is the loudest thing an advisory layer can
 * say, and the loudest thing an advisory layer can say is still advice — so the
 * band tones top out at the same amber/red used for "look at this", and no
 * caller may map a band onto a policy outcome.
 */
export function riskBandTone(band: string): Tone {
  switch (band) {
    case "LOW":
      return "secure";
    case "MEDIUM":
      return "advisory";
    case "HIGH":
    case "CRITICAL":
      return "critical";
    default:
      return "neutral";
  }
}

// --------------------------------------------------------------------------- //
// Provenance / authority / trust
// --------------------------------------------------------------------------- //

/** `packages/schemas/provenance.py :: AuthorityLevel`. Ordered lattice. */
export const AUTHORITY_LEVELS: ReadonlyArray<{ name: string; value: number; note: string }> = [
  { name: "MERCHANT_DATA", value: 10, note: "Merchant-controlled. Lowest authority, always tainted." },
  { name: "AGENT_PROPOSAL", value: 20, note: "An agent's proposal. Untrusted; also the cap on adapter input." },
  { name: "TRUSTED_INTERNAL_SERVICE", value: 30, note: "Produced by a trusted internal service — e.g. the server-owned merchant registry." },
  { name: "AUTHORIZATION", value: 40, note: "The kernel-issued authorization artifact." },
  { name: "SYSTEM_SECURITY_POLICY", value: 50, note: "System security policy." },
  { name: "USER_POLICY", value: 60, note: "User policy established at the trusted API boundary. Not cryptographically signed — no field claims it is." },
];

export function authorityName(level: number): string {
  return AUTHORITY_LEVELS.find((entry) => entry.value === level)?.name ?? `AUTHORITY_${level}`;
}

export function authorityTone(level: number): Tone {
  if (level <= 20) return "taint";
  if (level >= 50) return "secure";
  return "accent";
}

export function trustTone(trust: string): Tone {
  switch (trust.toLowerCase()) {
    case "authoritative":
      return "secure";
    case "trusted":
      return "accent";
    case "untrusted":
      return "taint";
    default:
      return "neutral";
  }
}

// --------------------------------------------------------------------------- //
// Protocol support
// --------------------------------------------------------------------------- //

export function protocolStatusTone(status: string): Tone {
  switch (status) {
    case "IMPLEMENTED":
      return "secure";
    case "PARTIAL":
      return "advisory";
    case "PLANNED":
      return "neutral";
    case "NOT_APPLICABLE":
      return "neutral";
    default:
      return "neutral";
  }
}
