"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, Menu, X } from "lucide-react";

import { Wordmark } from "./Brand";
import { PRIMARY_NAV, SECONDARY_NAV } from "./nav";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { cn } from "@/lib/format";

function isActiveRoute(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Navbar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuItemsRef = useRef<(HTMLAnchorElement | null)[]>([]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Close dropdown on Escape and return focus
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (dropdownOpen && event.key === "Escape") {
        setDropdownOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [dropdownOpen]);

  const isSecondaryActive = SECONDARY_NAV.some((item) => isActiveRoute(pathname, item.href));

  return (
    <header className="sticky top-0 z-40 w-full border-b border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)]/90 backdrop-blur-md transition-all duration-200">
      <div className="mx-auto flex h-16 max-w-[1480px] items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Left: Brand */}
        <div className="flex items-center gap-6 lg:gap-8">
          <Link href="/" className="flex items-center gap-2 rounded focus-visible:outline-2 focus-visible:outline-[#7C78E2]">
            <Wordmark compactText />
          </Link>

          {/* Desktop Primary Nav */}
          <nav aria-label="Primary" className="hidden lg:flex items-center gap-1">
            {PRIMARY_NAV.map((item) => {
              const active = isActiveRoute(pathname, item.href);
              const Icon = item.icon;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={item.blurb}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[13.5px] font-semibold transition-colors duration-150",
                    active
                      ? "text-[color:var(--pactra-indigo)] font-bold"
                      : "text-[color:var(--pactra-ink-secondary)] hover:bg-[color:var(--pactra-surface-2)] hover:text-[color:var(--pactra-ink)]"
                  )}
                >
                  <Icon
                    aria-hidden
                    className={cn(
                      "size-4 shrink-0 transition-colors",
                      active ? "text-[color:var(--pactra-indigo)]" : "text-[color:var(--pactra-ink-muted)]"
                    )}
                  />
                  <span>{item.label}</span>

                  {/* Active Indicator Underline */}
                  {active && (
                    <span
                      aria-hidden
                      className="absolute inset-x-2 -bottom-[13px] h-[2.5px] rounded-t-full bg-[#7C78E2]"
                    />
                  )}
                </Link>
              );
            })}

            {/* Desktop Secondary Dropdown Menu ("More ▾") */}
            <div ref={dropdownRef} className="relative ml-1">
              <button
                ref={buttonRef}
                type="button"
                onClick={() => setDropdownOpen((prev) => !prev)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
                    if (!dropdownOpen) {
                      e.preventDefault();
                      setDropdownOpen(true);
                      setTimeout(() => {
                        menuItemsRef.current[0]?.focus();
                      }, 0);
                    }
                  } else if (e.key === "Escape") {
                    setDropdownOpen(false);
                  }
                }}
                aria-expanded={dropdownOpen}
                aria-haspopup="true"
                aria-label="Secondary navigation options"
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-2 font-mono text-[13.5px] font-semibold transition-colors duration-150 cursor-pointer",
                  isSecondaryActive
                    ? "text-[color:var(--pactra-indigo)] font-bold"
                    : "text-[color:var(--pactra-ink-secondary)] hover:bg-[color:var(--pactra-surface-2)] hover:text-[color:var(--pactra-ink)]"
                )}
              >
                <span>More</span>
                <ChevronDown
                  className={cn(
                    "size-3.5 transition-transform duration-200",
                    dropdownOpen ? "rotate-180 text-[color:var(--pactra-indigo)]" : "text-[color:var(--pactra-ink-muted)]"
                  )}
                />
              </button>

              {/* Dropdown Menu */}
              {dropdownOpen && (
                <div
                  role="menu"
                  aria-orientation="vertical"
                  className="absolute right-0 mt-2 w-56 rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-1.5 shadow-lg backdrop-blur-md"
                >
                  <div className="px-2.5 py-1 font-mono text-[10px] font-bold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider">
                    Supporting Surfaces
                  </div>
                  {SECONDARY_NAV.map((item, idx) => {
                    const active = isActiveRoute(pathname, item.href);
                    const Icon = item.icon;

                    return (
                      <Link
                        key={item.href}
                        ref={(el) => {
                          menuItemsRef.current[idx] = el;
                        }}
                        href={item.href}
                        role="menuitem"
                        title={item.blurb}
                        onClick={() => setDropdownOpen(false)}
                        onKeyDown={(e) => {
                          if (e.key === "ArrowDown") {
                            e.preventDefault();
                            const next = (idx + 1) % SECONDARY_NAV.length;
                            menuItemsRef.current[next]?.focus();
                          } else if (e.key === "ArrowUp") {
                            e.preventDefault();
                            const prev = (idx - 1 + SECONDARY_NAV.length) % SECONDARY_NAV.length;
                            menuItemsRef.current[prev]?.focus();
                          } else if (e.key === "Escape") {
                            e.preventDefault();
                            setDropdownOpen(false);
                            buttonRef.current?.focus();
                          }
                        }}
                        className={cn(
                          "flex items-center justify-between rounded-md px-2.5 py-2 font-mono text-[12.5px] font-medium transition-colors",
                          active
                            ? "bg-[color:var(--pactra-surface-3)] text-[color:var(--pactra-indigo)] font-bold"
                            : "text-[color:var(--pactra-ink-secondary)] hover:bg-[color:var(--pactra-surface-2)] hover:text-[color:var(--pactra-ink)]"
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <Icon className="size-3.5 text-[color:var(--pactra-ink-muted)]" />
                          <span>{item.label}</span>
                        </div>
                        {item.href === "/risk" && (
                          <span className="font-mono text-[9px] font-bold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-1.5 py-0.5 rounded border border-[color:var(--pactra-warning)]/30 uppercase">
                            ADVISORY
                          </span>
                        )}
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          </nav>
        </div>

        {/* Right: Theme Toggle & Mobile Menu Trigger */}
        <div className="flex items-center gap-3">
          <div className="hidden sm:block">
            <ThemeToggle />
          </div>

          {/* Mobile Menu Button */}
          <button
            type="button"
            onClick={() => setMobileOpen((prev) => !prev)}
            aria-expanded={mobileOpen}
            aria-controls="pactra-mobile-nav"
            aria-label="Toggle navigation menu"
            className="inline-flex items-center justify-center rounded-md border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface-2)] p-2 text-[color:var(--pactra-ink)] hover:bg-[color:var(--pactra-surface-3)] lg:hidden"
          >
            {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Drawer / Overlay Navigation */}
      {mobileOpen && (
        <div
          id="pactra-mobile-nav"
          className="border-b border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 shadow-xl lg:hidden"
        >
          <div className="space-y-1">
            <div className="px-2 py-1 font-mono text-[10px] font-bold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider">
              Primary Navigation
            </div>
            {PRIMARY_NAV.map((item) => {
              const active = isActiveRoute(pathname, item.href);
              const Icon = item.icon;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2.5 font-mono text-[13px] font-semibold transition-colors",
                    active
                      ? "bg-[color:var(--pactra-surface-3)] text-[color:var(--pactra-indigo)] font-bold"
                      : "text-[color:var(--pactra-ink-secondary)] hover:bg-[color:var(--pactra-surface-2)] hover:text-[color:var(--pactra-ink)]"
                  )}
                >
                  <Icon className="size-4 text-[color:var(--pactra-indigo)]" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>

          <div className="mt-4 pt-3 border-t border-[color:var(--pactra-line)] space-y-1">
            <div className="px-2 py-1 font-mono text-[10px] font-bold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider">
              Supporting Surfaces
            </div>
            {SECONDARY_NAV.map((item) => {
              const active = isActiveRoute(pathname, item.href);
              const Icon = item.icon;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    "flex items-center justify-between rounded-md px-3 py-2 font-mono text-[12.5px] font-medium transition-colors",
                    active
                      ? "bg-[color:var(--pactra-surface-3)] text-[color:var(--pactra-indigo)] font-bold"
                      : "text-[color:var(--pactra-ink-secondary)] hover:bg-[color:var(--pactra-surface-2)] hover:text-[color:var(--pactra-ink)]"
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className="size-4 text-[color:var(--pactra-ink-muted)]" />
                    <span>{item.label}</span>
                  </div>
                  {item.href === "/risk" && (
                    <span className="font-mono text-[9px] font-bold text-[#B7791F] bg-[#B7791F]/15 px-1.5 py-0.5 rounded border border-[#B7791F]/30 uppercase">
                      ADVISORY
                    </span>
                  )}
                </Link>
              );
            })}
          </div>

          <div className="mt-4 pt-3 border-t border-[color:var(--pactra-line)] flex items-center justify-between px-2">
            <span className="font-mono text-[11px] text-[color:var(--pactra-ink-muted)]">Theme</span>
            <ThemeToggle />
          </div>
        </div>
      )}
    </header>
  );
}
