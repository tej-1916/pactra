"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";

export const BOOT_SESSION_KEY = "pactra_boot_seen";

export interface PactraBootRevealProps {
  onComplete?: () => void;
}

export function PactraBootReveal({ onComplete }: PactraBootRevealProps) {
  const shouldReduceMotion = useReducedMotion();
  const [isVisible, setIsVisible] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return sessionStorage.getItem(BOOT_SESSION_KEY) !== "true";
    } catch {
      return false;
    }
  });

  const active = isVisible && !shouldReduceMotion;

  useEffect(() => {
    if (!active) {
      onComplete?.();
      return;
    }

    // Mark as seen for subsequent route navigations
    try {
      sessionStorage.setItem(BOOT_SESSION_KEY, "true");
    } catch {
      // Ignore storage errors in restricted contexts
    }

    // Fast 1.1s timeline hand-off
    const timer = setTimeout(() => {
      setIsVisible(false);
      onComplete?.();
    }, 1150);

    return () => clearTimeout(timer);
  }, [active, onComplete]);

  if (!active) return null;

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          aria-hidden="true"
          initial={{ opacity: 1 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.35, ease: [0.4, 0, 0.2, 1] } }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#07080D] pointer-events-none select-none overflow-hidden"
        >
          {/* Faint Background Grid */}
          <div
            className="absolute inset-0 opacity-10 pointer-events-none"
            style={{
              backgroundImage:
                "linear-gradient(to right, rgba(210, 210, 238, 0.2) 1px, transparent 1px), linear-gradient(to bottom, rgba(210, 210, 238, 0.2) 1px, transparent 1px)",
              backgroundSize: "32px 32px",
            }}
          />

          {/* Technical Edge-Scan SVG Architecture Wireframe */}
          <div className="relative size-full max-w-2xl max-h-[600px] flex items-center justify-center p-6">
            <svg
              viewBox="0 0 600 500"
              className="w-full h-auto max-h-full"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* 1. Control Plane Outer Box Fragmented Edge Scan */}
              <motion.rect
                x="120"
                y="110"
                width="360"
                height="280"
                rx="16"
                stroke="rgba(255,255,255,0.74)"
                strokeWidth="1.5"
                strokeDasharray="1280"
                initial={{ strokeDashoffset: 1280, opacity: 0 }}
                animate={{ strokeDashoffset: 0, opacity: 1 }}
                transition={{ duration: 0.5, delay: 0.1, ease: "easeOut" }}
              />

              {/* Technical Header Label */}
              <motion.text
                x="140"
                y="132"
                fill="rgba(210,210,238,0.6)"
                fontSize="9"
                fontFamily="monospace"
                letterSpacing="2"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.3, delay: 0.25 }}
              >
                PACTRA CONTROL PLANE ARCHITECTURE
              </motion.text>

              {/* 2. Top External Inputs: AI BUYER -> MERCHANT OFFER */}
              <g transform="translate(200, 30)">
                <motion.rect
                  x="0"
                  y="0"
                  width="200"
                  height="28"
                  rx="6"
                  stroke="rgba(210,210,238,0.4)"
                  strokeWidth="1"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.3, delay: 0.15 }}
                />
                <text x="100" y="18" fill="rgba(255,255,255,0.85)" fontSize="10" fontFamily="monospace" textAnchor="middle" fontWeight="bold">
                  AI BUYER ➔ MERCHANT OFFER
                </text>
              </g>

              {/* Connector Down to ADMIT */}
              <motion.line
                x1="300"
                y1="58"
                x2="300"
                y2="110"
                stroke="rgba(210,210,238,0.35)"
                strokeWidth="1.2"
                strokeDasharray="4 4"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2, delay: 0.25 }}
              />

              {/* 3. ADMIT NODE */}
              <g transform="translate(180, 150)">
                <motion.rect
                  x="0"
                  y="0"
                  width="240"
                  height="42"
                  rx="8"
                  stroke="#7C78E2"
                  strokeWidth="1.5"
                  fill="rgba(32,33,96,0.6)"
                  initial={{ scale: 0.95, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ duration: 0.3, delay: 0.25 }}
                />
                <text x="20" y="25" fill="#FFFFFF" fontSize="13" fontFamily="monospace" fontWeight="bold">
                  ADMIT
                </text>
                <text x="220" y="25" fill="#9D9BE7" fontSize="9" fontFamily="monospace" textAnchor="end">
                  GATE 1 · POLICY
                </text>
              </g>

              {/* Supporting Secondary Nodes: POLICY & PROVENANCE */}
              <g transform="translate(180, 202)">
                <motion.rect
                  x="0"
                  y="0"
                  width="115"
                  height="22"
                  rx="4"
                  stroke="rgba(210,210,238,0.3)"
                  strokeWidth="1"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.2, delay: 0.35 }}
                />
                <text x="57" y="15" fill="#BBB9F5" fontSize="8.5" fontFamily="monospace" textAnchor="middle">
                  POLICY
                </text>

                <motion.rect
                  x="125"
                  y="0"
                  width="115"
                  height="22"
                  rx="4"
                  stroke="rgba(210,210,238,0.3)"
                  strokeWidth="1"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.2, delay: 0.35 }}
                />
                <text x="182" y="15" fill="#BBB9F5" fontSize="8.5" fontFamily="monospace" textAnchor="middle">
                  PROVENANCE
                </text>
              </g>

              {/* 4. BIND NODE */}
              <g transform="translate(180, 238)">
                <motion.rect
                  x="0"
                  y="0"
                  width="240"
                  height="42"
                  rx="8"
                  stroke="#7C78E2"
                  strokeWidth="1.5"
                  fill="rgba(32,33,96,0.6)"
                  initial={{ scale: 0.95, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ duration: 0.3, delay: 0.35 }}
                />
                <text x="20" y="25" fill="#FFFFFF" fontSize="13" fontFamily="monospace" fontWeight="bold">
                  BIND
                </text>
                <text x="220" y="25" fill="#9D9BE7" fontSize="9" fontFamily="monospace" textAnchor="end">
                  GATE 2 · AUTHORIZATION
                </text>
              </g>

              {/* Supporting Secondary Node: AUTHORIZATION */}
              <g transform="translate(200, 290)">
                <motion.rect
                  x="0"
                  y="0"
                  width="200"
                  height="20"
                  rx="4"
                  stroke="rgba(210,210,238,0.3)"
                  strokeWidth="1"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.2, delay: 0.42 }}
                />
                <text x="100" y="14" fill="#BBB9F5" fontSize="8.5" fontFamily="monospace" textAnchor="middle">
                  AUTHORIZATION · POLICY_AUTO
                </text>
              </g>

              {/* 5. EXECUTE NODE */}
              <g transform="translate(180, 322)">
                <motion.rect
                  x="0"
                  y="0"
                  width="240"
                  height="42"
                  rx="8"
                  stroke="#7C78E2"
                  strokeWidth="1.5"
                  fill="rgba(32,33,96,0.6)"
                  initial={{ scale: 0.95, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ duration: 0.3, delay: 0.45 }}
                />
                <text x="20" y="25" fill="#FFFFFF" fontSize="13" fontFamily="monospace" fontWeight="bold">
                  EXECUTE
                </text>
                <text x="220" y="25" fill="#9D9BE7" fontSize="9" fontFamily="monospace" textAnchor="end">
                  GATE 3 · EXECUTION
                </text>
              </g>

              {/* Connector Down Exit Control Plane */}
              <motion.line
                x1="300"
                y1="390"
                x2="300"
                y2="430"
                stroke="rgba(210,210,238,0.35)"
                strokeWidth="1.2"
                strokeDasharray="4 4"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2, delay: 0.5 }}
              />

              {/* 6. External Outputs: PAYMENT PROVIDER ➔ AUDIT / REPLAY */}
              <g transform="translate(140, 430)">
                <motion.rect
                  x="0"
                  y="0"
                  width="320"
                  height="30"
                  rx="6"
                  stroke="rgba(210,210,238,0.4)"
                  strokeWidth="1"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.3, delay: 0.52 }}
                />
                <text x="160" y="19" fill="rgba(255,255,255,0.85)" fontSize="9.5" fontFamily="monospace" textAnchor="middle" fontWeight="bold">
                  PAYMENT PROVIDER ➔ AUDIT / REPLAY (DECISION TRACE)
                </text>
              </g>

              {/* 7. Authority Signal Packet Travel: ADMIT -> BIND -> EXECUTE (420ms - 700ms) */}
              <motion.circle
                cx="300"
                r="5"
                fill="#9D9BE7"
                initial={{ cy: 171, opacity: 0 }}
                animate={{ cy: [171, 259, 343], opacity: [0, 1, 1, 0] }}
                transition={{ duration: 0.35, delay: 0.42, ease: "easeInOut" }}
              />
            </svg>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
