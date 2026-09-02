"use client";

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/format";

export type ButtonVariant = "primary" | "secondary" | "dark" | "outline" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  href?: string;
  showArrow?: boolean;
  icon?: ReactNode;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement | HTMLAnchorElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      href,
      showArrow = false,
      icon,
      children,
      className,
      disabled,
      type = "button",
      ...props
    },
    ref
  ) => {
    const baseStyles =
      "group relative inline-flex items-center justify-center font-semibold tracking-tight transition-all duration-200 ease-out focus-visible:outline-2 focus-visible:outline-[color:var(--pactra-indigo)] focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50 select-none cursor-pointer";

    const sizeStyles: Record<ButtonSize, string> = {
      sm: "h-9 rounded-full px-4 text-xs gap-1.5",
      md: "h-11 sm:h-12 rounded-full px-6 sm:px-7 text-sm gap-2",
      lg: "h-12 sm:h-14 rounded-full px-7 sm:px-8 text-base gap-2.5",
    };

    const variantStyles: Record<ButtonVariant, string> = {
      primary:
        "bg-[color:var(--pactra-indigo)] text-white shadow-md border border-[color:var(--pactra-indigo-bright)]/40 hover:bg-[color:var(--pactra-indigo-dark)] hover:border-[color:var(--pactra-indigo-bright)] hover:-translate-y-0.5 hover:shadow-lg active:translate-y-0 active:scale-[0.985]",
      secondary:
        "bg-[color:var(--pactra-surface-2)] text-[color:var(--pactra-ink)] border border-[color:var(--pactra-line-strong)] hover:bg-[color:var(--pactra-surface-3)] hover:border-[color:var(--pactra-indigo)] hover:text-[color:var(--pactra-indigo)] hover:-translate-y-0.5 hover:shadow-sm active:translate-y-0 active:scale-[0.985]",
      dark:
        "bg-white/10 backdrop-blur-md text-[#F7F7FF] border border-white/20 hover:bg-white/20 hover:border-[color:var(--pactra-indigo-bright)] hover:text-white hover:-translate-y-0.5 hover:shadow-md active:translate-y-0 active:scale-[0.985]",
      outline:
        "bg-transparent text-[color:var(--pactra-ink)] border border-[color:var(--pactra-line-strong)] hover:bg-[color:var(--pactra-surface-2)] hover:border-[color:var(--pactra-indigo)] active:scale-[0.985]",
      ghost:
        "bg-transparent text-[color:var(--pactra-ink-secondary)] hover:bg-[color:var(--pactra-surface-2)] hover:text-[color:var(--pactra-ink)] active:scale-[0.985]",
    };

    const content = (
      <>
        {/* Animated subtle border shimmer overlay for Primary Variant */}
        {variant === "primary" && (
          <span
            aria-hidden
            className="absolute inset-0 rounded-full p-[1px] bg-gradient-to-r from-[color:var(--pactra-indigo-bright)] via-[color:var(--pactra-periwinkle-light)] via-60% to-[color:var(--pactra-indigo-bright)] opacity-40 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none -z-10"
          />
        )}

        {icon && <span className="shrink-0">{icon}</span>}

        <span>{children}</span>

        {showArrow && (
          <ArrowRight
            className={cn(
              "size-4 shrink-0 transition-transform duration-200 ease-out group-hover:translate-x-1.5",
              variant === "primary" ? "text-white/90" : variant === "dark" ? "text-[color:var(--pactra-indigo-bright)]" : "text-[color:var(--pactra-indigo)]"
            )}
          />
        )}
      </>
    );

    if (href) {
      return (
        <Link
          href={href}
          className={cn(baseStyles, sizeStyles[size], variantStyles[variant], className)}
          ref={ref as React.Ref<HTMLAnchorElement>}
        >
          {content}
        </Link>
      );
    }

    return (
      <button
        type={type}
        disabled={disabled}
        className={cn(baseStyles, sizeStyles[size], variantStyles[variant], className)}
        ref={ref as React.Ref<HTMLButtonElement>}
        {...props}
      >
        {content}
      </button>
    );
  }
);

Button.displayName = "Button";
