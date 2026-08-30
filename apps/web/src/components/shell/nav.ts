import {
  Activity,
  Boxes,
  Crosshair,
  FileClock,
  Gauge,
  LayoutGrid,
  Store,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** One line, shown as the page's own subtitle and as the nav tooltip. */
  blurb: string;
}

/**
 * Primary navigation. Four items, and the list is deliberately short.
 *
 * These are the four questions a reader actually arrives with: what is this,
 * what did it do to a real transaction, what happens when someone attacks it,
 * and can any of it be verified after the fact.
 */
export const PRIMARY_NAV: NavItem[] = [
  {
    href: "/",
    label: "Overview",
    icon: LayoutGrid,
    blurb: "ADMIT → BIND → EXECUTE, system status, and where every number on this console comes from.",
  },
  {
    href: "/commerce",
    label: "Live Commerce",
    icon: Store,
    blurb: "One mission end to end: offer, policy, authorization, payment state, and its Decision Trace.",
  },
  {
    href: "/attack-lab",
    label: "Attack Lab",
    icon: Crosshair,
    blurb: "Adversarial scenarios, what each one targets, and what the kernel did about it.",
  },
  {
    href: "/audit",
    label: "Audit",
    icon: FileClock,
    blurb: "The hash chain, its verification, deterministic replay, and the evidence behind each event.",
  },
];

/**
 * Secondary navigation.
 *
 * RISK LIVES HERE, and that placement is a product decision rather than a
 * layout one. Risk is advisory: it grants no authority, changes no policy,
 * issues no authorization and executes no payment. Promoting it to primary
 * navigation would tell a reader it decides something, which is the single
 * most expensive misreading this console could invite.
 */
export const SECONDARY_NAV: NavItem[] = [
  {
    href: "/risk",
    label: "Risk",
    icon: Gauge,
    blurb: "Advisory risk index, factor contributions, and the evaluation disclosure. Advisory only.",
  },
  {
    href: "/adapters",
    label: "Adapters",
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

/**
 * Every navigable route, for the page-header lookup.
 *
 * `/missions` and `/transactions` are reachable and linked from Live Commerce
 * — they are the mission workbench and the payment observability surface — but
 * they are not primary destinations, so they carry blurbs here without taking a
 * slot in a four-item nav.
 */
export const ALL_ROUTES: NavItem[] = [
  ...PRIMARY_NAV,
  ...SECONDARY_NAV,
  {
    href: "/missions",
    label: "Mission workbench",
    icon: Store,
    blurb: "Run a mission through the kernel stage by stage, from intent to authorized payment.",
  },
  {
    href: "/transactions",
    label: "Transactions",
    icon: Store,
    blurb: "PaymentIntent observability and the state machine that governs it.",
  },
];
