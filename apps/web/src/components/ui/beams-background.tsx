"use client";

import { useEffect, useRef } from "react";
import { useReducedMotion } from "framer-motion";
import { cn } from "@/lib/format";

export interface PactraBeamsBackgroundProps {
  density?: number;
  speed?: number;
  aberration?: number;
  opacity?: number;
  beamColorPrimary?: string;
  beamColorSecondary?: string;
  beamColorCore?: string;
  dotIntensity?: number;
  className?: string;
  children?: React.ReactNode;
}

export function PactraBeamsBackground({
  density = 18,
  speed = 0.5,
  aberration = 0.3,
  opacity = 0.65,
  beamColorPrimary = "#5E58D2",
  beamColorSecondary = "#7C78E2",
  beamColorCore = "rgba(235, 234, 255, 0.7)",
  dotIntensity = 0.22,
  className,
  children,
}: PactraBeamsBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameIdRef = useRef<number | null>(null);
  const isVisibleRef = useRef<boolean>(true);
  const shouldReduceMotion = useReducedMotion();

  // IntersectionObserver to pause loop when off-screen (Section 13)
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]) {
          isVisibleRef.current = entries[0].isIntersecting;
        }
      },
      { threshold: 0.05 }
    );
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Main Canvas Holographic Beams Engine
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let time = 0;

    // Beam objects
    const beams: Array<{
      x: number;
      width: number;
      speed: number;
      phase: number;
      pulseFreq: number;
      color: string;
    }> = [];

    const initBeams = (w: number) => {
      beams.length = 0;
      // Adjust beam count dynamically based on width for mobile/tablet optimization (Section 15)
      const count = w < 640 ? Math.min(density, 10) : w < 1024 ? Math.min(density, 14) : density;

      for (let i = 0; i < count; i++) {
        beams.push({
          x: (w / (count + 1)) * (i + 1) + (Math.random() - 0.5) * 40,
          width: Math.random() * 65 + 35,
          speed: (Math.random() * 0.4 + 0.2) * speed,
          phase: Math.random() * Math.PI * 2,
          pulseFreq: Math.random() * 0.02 + 0.005,
          color: i % 2 === 0 ? beamColorPrimary : beamColorSecondary,
        });
      }
    };

    const handleResize = () => {
      if (!container || !canvas) return;
      const rect = container.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2); // Cap DPR at 2 for GPU efficiency

      width = rect.width;
      height = rect.height;

      canvas.width = width * dpr;
      canvas.height = height * dpr;

      ctx.scale(dpr, dpr);
      initBeams(width);
    };

    // ResizeObserver for reliable dimensions (Section 13)
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);
    handleResize();

    const drawFrame = () => {
      if (!ctx || width === 0 || height === 0) return;

      ctx.clearRect(0, 0, width, height);

      // Deep base background gradient (#15183F -> #242267 -> #312D8C)
      const bgGrad = ctx.createLinearGradient(0, 0, 0, height);
      bgGrad.addColorStop(0, "#15183F");
      bgGrad.addColorStop(0.6, "#202160");
      bgGrad.addColorStop(1, "#312D8C");
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, width, height);

      // Render vertical infrastructure beams
      beams.forEach((beam) => {
        const pulse = Math.sin(time * beam.pulseFreq + beam.phase) * 0.5 + 0.5;
        const currentOpacity = (0.15 + pulse * 0.35) * opacity;

        // Beam gradient from lower-middle focus point
        const beamGrad = ctx.createLinearGradient(beam.x, height, beam.x, 0);
        beamGrad.addColorStop(0, "rgba(21, 24, 63, 0)");
        beamGrad.addColorStop(0.3, beam.color);
        beamGrad.addColorStop(0.7, beamColorCore);
        beamGrad.addColorStop(1, "rgba(21, 24, 63, 0)");

        // Primary Beam Body
        ctx.save();
        ctx.globalAlpha = currentOpacity;
        ctx.fillStyle = beamGrad;

        // Subtle optical depth offset (Section 3: Optical depth aberration)
        const offset = Math.sin(time * 0.01 + beam.phase) * aberration * 8;

        ctx.beginPath();
        ctx.moveTo(beam.x - beam.width / 2 + offset, height);
        ctx.lineTo(beam.x - beam.width / 4, 0);
        ctx.lineTo(beam.x + beam.width / 4, 0);
        ctx.lineTo(beam.x + beam.width / 2 + offset, height);
        ctx.closePath();
        ctx.fill();

        ctx.restore();
      });

      // Central localized glow near the control plane (Section 10)
      const glowGrad = ctx.createRadialGradient(
        width / 2,
        height * 0.55,
        20,
        width / 2,
        height * 0.55,
        width * 0.45
      );
      glowGrad.addColorStop(0, "rgba(124, 120, 226, 0.25)");
      glowGrad.addColorStop(0.5, "rgba(94, 88, 210, 0.12)");
      glowGrad.addColorStop(1, "rgba(21, 24, 63, 0)");
      ctx.fillStyle = glowGrad;
      ctx.fillRect(0, 0, width, height);
    };

    // Animation Loop
    const loop = () => {
      if (isVisibleRef.current) {
        time += 1;
        drawFrame();
      }

      if (!shouldReduceMotion) {
        animFrameIdRef.current = requestAnimationFrame(loop);
      }
    };

    // Single static frame if reduced motion is active (Section 14)
    if (shouldReduceMotion) {
      drawFrame();
    } else {
      loop();
    }

    return () => {
      if (animFrameIdRef.current) {
        cancelAnimationFrame(animFrameIdRef.current);
      }
      resizeObserver.disconnect();
    };
  }, [
    density,
    speed,
    aberration,
    opacity,
    beamColorPrimary,
    beamColorSecondary,
    beamColorCore,
    shouldReduceMotion,
  ]);

  return (
    <div
      ref={containerRef}
      className={cn("relative w-full overflow-hidden bg-[#15183F]", className)}
    >
      {/* 1. Canvas Layer: Holographic Beams (Section 2 & 16) */}
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="absolute inset-0 size-full pointer-events-none"
      />

      {/* 2. Precise Dot Grid Infrastructure Field (Section 5 & 6) */}
      <div
        aria-hidden="true"
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: `radial-gradient(circle, rgba(157, 155, 231, ${dotIntensity}) 1.2px, transparent 1.2px)`,
          backgroundSize: "24px 24px",
          maskImage: "radial-gradient(ellipse at 50% 50%, black 45%, transparent 92%)",
          WebkitMaskImage: "radial-gradient(ellipse at 50% 50%, black 45%, transparent 92%)",
        }}
      />

      {/* 3. Extremely Faint Scanlines Texture (Section 11) */}
      <div
        aria-hidden="true"
        className="absolute inset-0 pointer-events-none opacity-5 bg-[linear-gradient(to_bottom,rgba(255,255,255,0.15)_1px,transparent_1px)] bg-[size:100%_4px]"
      />

      {/* 4. Soft Edge Vignette (#15183F fade) (Section 12) */}
      <div
        aria-hidden="true"
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "radial-gradient(ellipse at 50% 50%, transparent 60%, #15183F 100%)",
        }}
      />

      {/* Foreground Content */}
      <div className="relative z-10">{children}</div>
    </div>
  );
}
