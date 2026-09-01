"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

interface ProtocolExample {
  id: string;
  name: string;
  family: string;
  status: "IMPLEMENTED" | "PARTIAL" | "ROADMAP";
  inputFormat: string;
  inputJson: string;
  translationRules: string[];
  candidateJson: string;
  kernelHandoffNote: string;
}

const EXAMPLES: ProtocolExample[] = [
  {
    id: "mcp-tools-call",
    name: "Model Context Protocol (MCP)",
    family: "Tool Adapter",
    status: "PARTIAL",
    inputFormat: "JSON-RPC 2.0 (tools/call)",
    inputJson: JSON.stringify(
      {
        jsonrpc: "2.0",
        id: "call_mcp_0942",
        method: "tools/call",
        params: {
          name: "pactra.buy_item",
          arguments: {
            merchant_id: "merch_cloud_computing",
            product_id: "prod_server_vm",
            quantity: 1,
            amount_inr: 4999,
          },
        },
      },
      null,
      2
    ),
    translationRules: [
      "Translates tools/call envelope to CandidateMerchantOffer / CandidateOperation.",
      "Rejects any protocol revision outside 2024-11-05, 2025-03-26, 2025-06-18.",
      "Does NOT act as an MCP server (no initialize, no prompts/resources/SSE).",
      "Strips unauthenticated caller identity claims.",
    ],
    candidateJson: JSON.stringify(
      {
        candidate_type: "CandidateMerchantOffer",
        source_protocol: "MCP (tools/call)",
        merchant_proposal: {
          merchant_id: "merch_cloud_computing",
          product_id: "prod_server_vm",
          quantity: 1,
          amount_inr: 4999,
          currency: "INR",
        },
        authority_level: "AGENT_PROPOSAL",
        trust_level: "UNTRUSTED",
        is_tainted: true,
      },
      null,
      2
    ),
    kernelHandoffNote:
      "Handed to Security Kernel for ADMIT evaluation. Even valid JSON-RPC translates to an UNTRUSTED candidate.",
  },
  {
    id: "pactra-commerce",
    name: "pactra.commerce.v1",
    family: "Commerce Adapter",
    status: "IMPLEMENTED",
    inputFormat: "PACTRA Native Catalog JSON",
    inputJson: JSON.stringify(
      {
        catalog_version: "v1.0",
        merchant_id: "merch_quick_groceries",
        product_id: "prod_artisanal_coffee",
        price_inr: 1200,
        currency: "INR",
        metadata: { promo_code: "WELCOME20", seller_tier: "UNVERIFIED" },
      },
      null,
      2
    ),
    translationRules: [
      "Strict JSON type validation ahead of lax DTO.",
      "Preserves raw merchant strings with explicit taint tagging.",
      "Zero side effects: creates no payment, mutates no policy.",
    ],
    candidateJson: JSON.stringify(
      {
        candidate_type: "CandidateMerchantOffer",
        source_protocol: "pactra.commerce.v1",
        merchant_proposal: {
          merchant_id: "merch_quick_groceries",
          product_id: "prod_artisanal_coffee",
          amount_inr: 1200,
          currency: "INR",
        },
        authority_level: "MERCHANT_PROPOSAL",
        trust_level: "UNTRUSTED",
        is_tainted: true,
      },
      null,
      2
    ),
    kernelHandoffNote:
      "Handed to Security Kernel for ADMIT evaluation. Merchant price and product are verified against user policy constraints.",
  },
  {
    id: "pactra-intent",
    name: "pactra.authorization-intent.v1",
    family: "Payment Authorization Adapter",
    status: "IMPLEMENTED",
    inputFormat: "External Authorization Intent",
    inputJson: JSON.stringify(
      {
        intent_version: "v1",
        merchant_id: "merch_cloud_computing",
        max_amount_inr: 5000,
        expires_at: "2026-09-01T18:00:00Z",
      },
      null,
      2
    ),
    translationRules: [
      "StrictInt money validation and timezone-aware expiry enforcement.",
      "Forbids and strips reserved names (nonce, signature, transaction_digest, authorization_id).",
      "Outputs CandidateAuthorizationRequest (NOT an issued authorization).",
    ],
    candidateJson: JSON.stringify(
      {
        candidate_type: "CandidateAuthorizationRequest",
        source_protocol: "pactra.authorization-intent.v1",
        requested_bounds: {
          merchant_id: "merch_cloud_computing",
          max_amount_inr: 5000,
          expires_at: "2026-09-01T18:00:00Z",
        },
        authority_level: "USER_POLICY_PROPOSAL",
        trust_level: "UNTRUSTED_INTENT",
      },
      null,
      2
    ),
    kernelHandoffNote:
      "Handed to Security Kernel for BIND evaluation. Mints cryptographic authorization only if policy passes.",
  },
];

export function AdapterFlowDemo() {
  const [selectedId, setSelectedId] = useState<string>("mcp-tools-call");
  const active = EXAMPLES.find((e) => e.id === selectedId) || (EXAMPLES[0] as ProtocolExample);

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--pactra-line)] pb-3">
        <div>
          <h2 className="font-display text-[15px] font-bold text-white uppercase tracking-wider">
            INPUT → TRANSLATION → CANDIDATE PREVIEW
          </h2>
          <p className="text-[12px] text-[color:var(--pactra-ink-muted)]">
            How external protocols are translated into unprivileged Canonical Candidates with zero side effects.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="secure" variant="outline">
            TRANSLATION SIDE EFFECTS = ZERO
          </Badge>
          <Badge tone="advisory" variant="outline">
            CANONICAL CANDIDATE
          </Badge>
        </div>
      </div>

      {/* Protocol Tabs */}
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.id}
            type="button"
            onClick={() => setSelectedId(ex.id)}
            className={`rounded-md px-3 py-1.5 font-mono text-[11.5px] font-bold transition-colors ${
              selectedId === ex.id
                ? "bg-[#15183F] text-white border border-[#7C78E2]"
                : "bg-[color:var(--pactra-surface-2)] text-[color:var(--pactra-ink-secondary)] hover:text-white border border-transparent"
            }`}
          >
            {ex.name}
            <span className="ml-2 text-[10px] text-[#9D9BE7]">[{ex.status}]</span>
          </button>
        ))}
      </div>

      {/* 3-Column Translation Stage Grid */}
      <div className="grid gap-4 lg:grid-cols-3 items-stretch font-mono text-[11.5px]">
        {/* Column 1: External Input */}
        <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between space-y-3">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-white/5">
              <span className="text-[10px] font-bold text-[color:var(--pactra-critical)] uppercase tracking-wider">
                1. EXTERNAL UNTRUSTED INPUT
              </span>
              <Badge tone="critical" variant="outline">
                TAINTED
              </Badge>
            </div>
            <div className="text-[11px] text-[color:var(--pactra-ink-muted)] pt-2 pb-1">
              Format: {active.inputFormat}
            </div>
            <pre className="rounded bg-[#11131b] p-3 text-[11px] text-[color:var(--pactra-ink-secondary)] overflow-x-auto border border-white/5 max-h-[220px]">
              {active.inputJson}
            </pre>
          </div>
          <div className="text-[10.5px] text-[color:var(--pactra-ink-muted)]">
            External messages possess zero authority.
          </div>
        </div>

        {/* Column 2: Translation Rules */}
        <div className="rounded-lg border border-[#7C78E2]/30 bg-[#15183F]/60 p-4 flex flex-col justify-between space-y-3">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-white/5">
              <span className="text-[10px] font-bold text-[#9D9BE7] uppercase tracking-wider">
                2. ADAPTER TRANSLATION
              </span>
              <Badge tone="accent" variant="outline">
                ZERO SIDE EFFECTS
              </Badge>
            </div>
            <div className="text-[11px] text-[color:var(--pactra-ink-muted)] pt-2 pb-2">
              Translation Guarantees:
            </div>
            <ul className="space-y-2 text-[11px] text-[color:var(--pactra-ink-secondary)]">
              {active.translationRules.map((rule, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <CheckCircle2 className="size-3.5 text-[#7C78E2] shrink-0 mt-0.5" />
                  <span>{rule}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="text-[10.5px] text-[color:var(--pactra-ink-muted)]">
            Adapter trust ≠ Caller authority.
          </div>
        </div>

        {/* Column 3: Canonical Candidate */}
        <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between space-y-3">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-white/5">
              <span className="text-[10px] font-bold text-[color:var(--pactra-success)] uppercase tracking-wider">
                3. CANONICAL CANDIDATE
              </span>
              <Badge tone="secure" variant="outline">
                UNPRIVILEGED
              </Badge>
            </div>
            <div className="text-[11px] text-[color:var(--pactra-ink-muted)] pt-2 pb-1">
              Kernel Ingestion Payload:
            </div>
            <pre className="rounded bg-[#11131b] p-3 text-[11px] text-[#9D9BE7] overflow-x-auto border border-white/5 max-h-[220px]">
              {active.candidateJson}
            </pre>
          </div>
          <div className="text-[10.5px] text-[color:var(--pactra-ink-muted)]">
            {active.kernelHandoffNote}
          </div>
        </div>
      </div>
    </div>
  );
}
