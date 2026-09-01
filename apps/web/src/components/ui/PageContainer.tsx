"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/format";

export type PageContainerVariant = "standard" | "wide";

export interface PageContainerProps {
  variant?: PageContainerVariant;
  children: ReactNode;
  className?: string;
}

export function PageContainer({
  variant = "standard",
  children,
  className,
}: PageContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full transition-all duration-200",
        variant === "wide" ? "max-w-[1480px]" : "max-w-[1280px]",
        "px-4 sm:px-6 lg:px-8 py-6 sm:py-8",
        className
      )}
    >
      {children}
    </div>
  );
}
