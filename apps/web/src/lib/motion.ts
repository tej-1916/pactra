/**
 * PACTRA Motion System Tokens & Variants — Phase 1 Design Foundation
 *
 * Motion Principles:
 * - FAST (120–180ms): Micro-interactions, button hovers, badge toggles.
 * - NORMAL (200–320ms): Panel reveals, drawer expansion, tab switching.
 * - LARGE (350–550ms): Pipeline state transitions, node graph active flow pulses.
 *
 * Motion must be smooth, physical, and premium — never bouncy, playful, or noisy.
 * Every animation respects prefers-reduced-motion via Framer Motion's reducedMotion="user".
 */

export const DURATION = {
  FAST: 0.15,
  NORMAL: 0.25,
  LARGE: 0.45,
} as const;

export const EASING = {
  PREMIUM: [0.16, 1, 0.3, 1], // Custom cubic-bezier for smooth physical deceleration
  EASE_IN_OUT: [0.4, 0, 0.2, 1],
  EASE_OUT: [0, 0, 0.2, 1],
} as const;

export const MOTION_VARIANTS = {
  fadeInUp: {
    initial: { opacity: 0, y: 6 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: -4 },
    transition: { duration: DURATION.NORMAL, ease: EASING.PREMIUM },
  },
  glassPanelReveal: {
    initial: { opacity: 0, scale: 0.98, y: 8 },
    animate: { opacity: 1, scale: 1, y: 0 },
    exit: { opacity: 0, scale: 0.98, y: 4 },
    transition: { duration: DURATION.NORMAL, ease: EASING.PREMIUM },
  },
  traceExpansion: {
    initial: { height: 0, opacity: 0 },
    animate: { height: "auto", opacity: 1 },
    exit: { height: 0, opacity: 0 },
    transition: { duration: DURATION.NORMAL, ease: EASING.PREMIUM },
  },
  pulseNode: {
    initial: { scale: 1, opacity: 0.8 },
    animate: {
      scale: [1, 1.06, 1],
      opacity: [0.8, 1, 0.8],
      transition: {
        duration: 2.2,
        repeat: Infinity,
        ease: "easeInOut",
      },
    },
  },
  activeEdgeFlow: {
    initial: { strokeDashoffset: 24 },
    animate: { strokeDashoffset: 0 },
    transition: {
      duration: 1.5,
      repeat: Infinity,
      ease: "linear",
    },
  },
} as const;
