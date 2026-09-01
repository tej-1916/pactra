import type { Metadata } from "next";
import { AuditReplayConsole } from "@/components/audit/AuditReplayConsole";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Audit & Replay | PACTRA",
  description: "Inspect deterministic transaction evidence and replay audit logs.",
};

export default function AuditPage() {
  return <AuditReplayConsole />;
}
