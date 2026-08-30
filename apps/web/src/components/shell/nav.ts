import {
  Activity,
  Boxes,
  CreditCard,
  Crosshair,
  FileClock,
  Gauge,
  LayoutGrid,
  Route,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** One line, shown as the page's own subtitle and as the nav tooltip. */
  blurb: string;
}

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/",
    label: "Command Center",
    icon: LayoutGrid,
    blurb: "System posture, security invariants, and where every number comes from.",
  },
  {
    href: "/missions",
    label: "Missions",
    icon: Route,
    blurb: "User intent through the kernel to an authorized payment, stage by stage.",
  },
  {
    href: "/attack-lab",
    label: "Attack Lab",
    icon: Crosshair,
    blurb: "Adversarial scenarios, what each one targets, and what the kernel did about it.",
  },
  {
    href: "/transactions",
    label: "Transactions",
    icon: CreditCard,
    blurb: "PaymentIntent observability and the state machine that governs it.",
  },
  {
    href: "/audit",
    label: "Audit & Replay",
    icon: FileClock,
    blurb: "The hash chain, its verification, and deterministic reconstruction from history.",
  },
  {
    href: "/risk",
    label: "Risk Intelligence",
    icon: Gauge,
    blurb: "Advisory risk index, factor contributions, and the evaluation disclosure.",
  },
  {
    href: "/adapters",
    label: "Protocol Adapters",
    icon: Boxes,
    blurb: "The translation boundary and exactly what PACTRA does and does not speak.",
  },
  {
    href: "/system",
    label: "System",
    icon: Activity,
    blurb: "Architecture, vocabulary, and the documented boundaries of the contract.",
  },
];
