"use client";

import { useState } from "react";
import { FileSignature, KeyRound, Loader2, ShieldCheck, TerminalSquare } from "lucide-react";

import { HashDisplay } from "@/components/ui/HashDisplay";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { inr, timestamp } from "@/lib/format";
import type { ApprovalChallenge, ApprovalSubmission } from "@/lib/types/pactra";

/**
 * The USER_ED25519 approval step.
 *
 * THE CONSOLE DOES NOT SIGN. The demo signing key lives in a file outside this
 * repository, and the only thing that ever touches it is the external signer
 * (`scripts/pactra_demo_signer.py`). A browser-held signing key would be a
 * key distributed to every viewer of this page, which is the opposite of the
 * property the proof is supposed to demonstrate — so there is no key input on
 * this panel, no WebCrypto call, and no place a private key could be pasted.
 *
 * What this panel does is the honest remainder: display the exact canonical
 * bytes the server rebuilt, show the transaction those bytes commit to, hand
 * the operator the command that signs them elsewhere, and carry the resulting
 * signature back to the kernel for verification.
 */
export function SignedApprovalPanel({
  challenge,
  onApprove,
  approving,
}: {
  challenge: ApprovalChallenge;
  onApprove: (submission: ApprovalSubmission) => void;
  approving?: boolean;
}) {
  const [signature, setSignature] = useState("");

  const trimmed = signature.trim().toLowerCase();
  const wellFormed = /^[0-9a-f]{128}$/.test(trimmed);
  // Only the SHAPE is checked here. Whether the signature verifies is the
  // kernel's answer to give, and a console that guessed would be claiming an
  // authority it does not have.
  const shapeHint =
    trimmed.length === 0
      ? null
      : wellFormed
        ? null
        : `Expected 128 lowercase hexadecimal characters; got ${trimmed.length}.`;

  const command = [
    "python scripts/pactra_demo_signer.py sign",
    `  --mission-id ${challenge.mission_id}`,
    `  --signing-key-id ${challenge.signing_key_id}`,
    "  --private-key-path ~/.pactra/demo-approver.pem",
    "  --submit",
  ].join(" \\\n");

  return (
    <Panel
      title="Approval proof required"
      subtitle="Policy returned REQUIRE_APPROVAL, so this authorization activates only against an Ed25519 signature over the exact transaction below."
    >
      <div className="space-y-4">
        <div className="rounded-lg border border-[color:var(--color-accent)]/25 bg-[color:var(--color-accent)]/[0.05] p-3.5">
          <p className="label-xs mb-2.5 flex items-center gap-1.5 text-[color:var(--color-accent)]">
            <KeyRound aria-hidden className="size-3.5" />
            What the signature will commit to
          </p>
          <KeyValueGrid columns={3}>
            <KeyValue label="Merchant"><span className="num">{challenge.transaction.merchant}</span></KeyValue>
            <KeyValue label="Product"><span className="num">{challenge.transaction.product}</span></KeyValue>
            <KeyValue label="Quantity"><span className="num">{challenge.transaction.quantity}</span></KeyValue>
            <KeyValue label="Amount"><span className="num">{inr(challenge.transaction.amount)}</span></KeyValue>
            <KeyValue label="Currency"><span className="num">{challenge.transaction.currency}</span></KeyValue>
            <KeyValue label="Expires at"><span className="num">{timestamp(challenge.transaction.expiry)}</span></KeyValue>
          </KeyValueGrid>
          <div className="mt-3 border-t border-[color:var(--color-accent)]/20 pt-2.5">
            <KeyValueGrid columns={2}>
              <KeyValue label="Transaction digest">
                <HashDisplay value={challenge.transaction_digest} head={12} tail={8} />
              </KeyValue>
              <KeyValue
                label="Signing key id"
                hint="Server-selected. The request carries no public key and no algorithm choice, so a caller cannot nominate a key it controls."
              >
                <span className="num">{challenge.signing_key_id}</span>
              </KeyValue>
            </KeyValueGrid>
          </div>
        </div>

        <div>
          <p className="label-xs mb-2 flex items-center gap-1.5 text-[color:var(--color-ink-3)]">
            <FileSignature aria-hidden className="size-3.5" />
            Canonical message — the exact bytes to sign
          </p>
          <HashDisplay value={challenge.approval_message_hex} head={32} tail={16} label="approval_message_hex" />
          <p className="mt-1.5 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
            Domain-separated and rebuilt by the server from durable state on every request. The
            signer independently reconstructs these bytes from the challenge fields and refuses to
            sign if the two disagree, so a tampered challenge cannot become a signature.
          </p>
        </div>

        <div>
          <p className="label-xs mb-2 flex items-center gap-1.5 text-[color:var(--color-ink-3)]">
            <TerminalSquare aria-hidden className="size-3.5" />
            Sign it outside PACTRA
          </p>
          <pre className="num overflow-x-auto rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2,transparent)] p-3 text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)]">
            {command}
          </pre>
          <p className="mt-1.5 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
            The signer displays this transaction, asks for confirmation, and signs with a key held
            at <span className="num">0600</span> outside the repository. With{" "}
            <span className="num">--submit</span> it posts the proof itself and this panel needs
            nothing further — refresh to see the result. Drop{" "}
            <span className="num">--submit</span> to have it print the signature, then paste it
            below.
          </p>
        </div>

        <div className="border-t border-[color:var(--color-line)] pt-3">
          <label htmlFor="approval-signature" className="label-xs mb-2 block text-[color:var(--color-ink-3)]">
            Signature from the external signer
          </label>
          <textarea
            id="approval-signature"
            value={signature}
            onChange={(event) => setSignature(event.target.value)}
            spellCheck={false}
            rows={3}
            placeholder="128 lowercase hexadecimal characters"
            aria-describedby="approval-signature-hint"
            className="num w-full resize-y rounded-lg border border-[color:var(--color-line)] bg-transparent p-2.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)] outline-none focus:border-[color:var(--color-accent)]/50"
          />
          <p id="approval-signature-hint" className="mt-1.5 text-[11px] text-[color:var(--color-critical)]">
            {shapeHint ?? " "}
          </p>
          <button
            type="button"
            disabled={!wellFormed || approving}
            onClick={() =>
              onApprove({ signing_key_id: challenge.signing_key_id, signature: trimmed })
            }
            className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-secure)]/45 bg-[color:var(--color-secure)]/12 px-3 py-1.5 text-[12px] font-semibold text-[color:var(--color-secure)] transition-colors hover:bg-[color:var(--color-secure)]/20 disabled:opacity-50"
          >
            {approving ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <ShieldCheck aria-hidden className="size-3.5" />
            )}
            Submit approval proof
          </button>
        </div>
      </div>
    </Panel>
  );
}
