"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";

import { ApiStatus } from "./ApiStatus";
import { Wordmark } from "./Brand";
import { NAV_ITEMS } from "./nav";
import { cn } from "@/lib/format";

/**
 * The application shell's navigation.
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
          className="fixed inset-0 z-40 bg-black/60 lg:hidden"
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

        <ul className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV_ITEMS.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  title={item.blurb}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[12.5px] font-medium transition-colors",
                    active
                      ? "bg-[color:var(--color-surface-3)] text-[color:var(--color-ink)]"
                      : "text-[color:var(--color-ink-3)] hover:bg-[color:var(--color-surface-2)] hover:text-[color:var(--color-ink-2)]",
                  )}
                >
                  {active ? (
                    <span
                      aria-hidden
                      className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-[color:var(--color-accent)]"
                    />
                  ) : null}
                  <Icon
                    aria-hidden
                    className={cn(
                      "size-4 shrink-0",
                      active ? "text-[color:var(--color-accent)]" : "text-[color:var(--color-ink-4)]",
                    )}
                  />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>

        <ApiStatus />
      </nav>
    </>
  );
}
