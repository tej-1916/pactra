import type { Metadata } from "next";
import { AttackLabConsole } from "@/components/attack-lab/AttackLabConsole";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Attack Lab — PACTRA" };

export default function AttackLabPage() {
  return <AttackLabConsole />;
}
