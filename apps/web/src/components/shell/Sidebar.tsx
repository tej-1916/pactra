"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";

import { ApiStatus } from "./ApiStatus";
import { Wordmark } from "./Brand";
import { PRIMARY_NAV, SECONDARY_NAV, type NavItem } from "./nav";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { cn } from "@/lib/format";

/**
 * The application shell's navigation.
 *
 * Two groups, and the split carries meaning rather than saving space. The four
 * primary items are the questions a reader arrives with. The secondary group
 * holds Risk, Adapters and System — and Risk is there BECAUSE it is advisory:
 * a risk score decides nothing in PACTRA, and a nav that gave it equal billing
 * with the decision surfaces would imply otherwise.
 *
 * Desktop-first, as the demo requires, but it collapses to a disclosure below
 * `lg` rather than disappearing — a security console that cannot be navigated
 * on a laptop screen at 1366×768 is not a console.
 */
export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="pactra-nav"
        className="fixed top-3 left-3 z-50 inline-flex items-center gap-2 rounded-md border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-2)] px-2.5 py-1.5 text-[12px] font-medium text-[color:var(--color-ink-2)] lg:hidden"
      >
        {open ? <X aria-hidden className="size-4" /> : <Menu aria-hidden className="size-4" />}
        Menu
      </button>

      {open ? (
        <div
          aria-hidden
          onClick={() => setOpen(false)}
          className="scrim fixed inset-0 z-40 lg:hidden"
        />
      ) : null}

      <nav
        id="pactra-nav"
        aria-label="Primary"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r border-[color:var(--color-line)] bg-[color:var(--color-surface)]/95 backdrop-blur-sm transition-transform lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="border-b border-[color:var(--color-line)] px-4 pt-14 pb-4 lg:pt-4">
          <Link href="/" className="block rounded" onClick={() => setOpen(false)}>
            <Wordmark />
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          <ul className="space-y-0.5">
            {PRIMARY_NAV.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                pathname={pathname}
                onNavigate={() => setOpen(false)}
              />
            ))}
          </ul>

          <p className="label-xs mt-5 mb-1.5 px-2.5 text-[color:var(--color-ink-4)]">
            Supporting
          </p>
          <ul className="space-y-0.5">
            {SECONDARY_NAV.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                pathname={pathname}
                onNavigate={() => setOpen(false)}
                secondary
              />
            ))}
          </ul>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-[color:var(--color-line)] px-3 py-2">
          <span className="label-xs text-[color:var(--color-ink-4)]">Theme</span>
          <ThemeToggle />
        </div>

        <ApiStatus />
      </nav>
    </>
  );
}

function NavLink({
  item,
  pathname,
  onNavigate,
  secondary = false,
}: {
  item: NavItem;
  pathname: string;
  onNavigate: () => void;
  secondary?: boolean;
}) {
  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
  const Icon = item.icon;
  return (
    <li>
      <Link
        href={item.href}
        title={item.blurb}
        aria-current={active ? "page" : undefined}
        onClick={onNavigate}
        className={cn(
          "group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 font-medium transition-colors",
          secondary ? "text-[12px]" : "text-[12.5px]",
          active
            ? "bg-[color:var(--color-surface-3)] text-[color:var(--color-ink)]"
            : "text-[color:var(--color-ink-3)] hover:bg-[color:var(--color-surface-2)] hover:text-[color:var(--color-ink-2)]",
        )}
      >
        {active ? (
          <span
            aria-hidden
            className="gradient-path absolute inset-y-1.5 left-0 w-[2px] rounded-full"
          />
        ) : null}
        <Icon
          aria-hidden
          className={cn(
            "shrink-0",
            secondary ? "size-3.5" : "size-4",
            active ? "text-[color:var(--color-accent)]" : "text-[color:var(--color-ink-4)]",
          )}
        />
        {item.label}
      </Link>
    </li>
  );
}
