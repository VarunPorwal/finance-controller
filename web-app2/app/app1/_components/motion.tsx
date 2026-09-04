"use client";

// Motion primitives: a counting number, a ring gauge, a sparkline, a
// slide-over panel. All CSS/SVG and framer-motion; no WebGL here.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { animate, motion, AnimatePresence, useInView, useReducedMotion } from "framer-motion";
import { clsx } from "clsx";
import { X } from "lucide-react";

/** Counts from 0 to `value` once it scrolls into view. Renders via `format`. */
export function CountUp({
  value,
  format = (n) => Math.round(n).toLocaleString("en-IN"),
  duration = 1.1,
  className,
  delay = 0,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  className?: string;
  delay?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -10% 0px" });
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(() => format(reduced ? value : 0));
  // The value last shown, so an update animates from where it was, never from 0.
  const shown = useRef<number | null>(null);

  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      shown.current = value;
      setDisplay(format(value));
      return;
    }
    const from = shown.current ?? 0;
    const isUpdate = shown.current !== null;
    shown.current = value;
    if (isUpdate && from === value) return;
    const controls = animate(from, value, {
      duration: isUpdate ? 0.35 : duration,
      delay: isUpdate ? 0 : delay,
      ease: [0.2, 0.8, 0.2, 1],
      onUpdate: (v) => setDisplay(format(v)),
    });
    // A throttled tab (projector switching, background window) starves the
    // frame loop; land on the real figure by wall clock regardless.
    const settle = window.setTimeout(() => {
      controls.stop();
      setDisplay(format(value));
    }, (duration + delay) * 1000 + 400);
    return () => {
      controls.stop();
      window.clearTimeout(settle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inView, value, reduced]);

  return (
    <span ref={ref} className={className}>
      {display}
    </span>
  );
}

/** A ring that fills to `fraction` (0..1). One per page at most. */
export function Ring({
  fraction,
  size = 120,
  stroke = 8,
  tone = "ok",
  children,
  className,
  trackOpacity = 0.12,
}: {
  fraction: number;
  size?: number;
  stroke?: number;
  tone?: "ok" | "warn" | "bad" | "model" | "brand";
  children?: ReactNode;
  className?: string;
  trackOpacity?: number;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const color =
    tone === "ok"
      ? "var(--a1-ok)"
      : tone === "warn"
        ? "var(--a1-warn)"
        : tone === "bad"
          ? "var(--a1-bad)"
          : tone === "model"
            ? "var(--a1-model)"
            : "var(--a1-brand)";
  const clamped = Math.max(0, Math.min(1, fraction));
  return (
    <div className={clsx("relative inline-flex items-center justify-center", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="currentColor" strokeOpacity={trackOpacity} strokeWidth={stroke} fill="none" />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - clamped) }}
          transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>
    </div>
  );
}

export function Sparkline({
  values,
  width = 120,
  height = 32,
  tone = "ok",
  className,
  fill = true,
}: {
  values: number[];
  width?: number;
  height?: number;
  tone?: "ok" | "warn" | "bad" | "brand" | "ink";
  className?: string;
  fill?: boolean;
}) {
  if (values.length < 2) return <div style={{ width, height }} />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * (width - 2) + 1,
    height - 2 - ((v - min) / span) * (height - 4),
  ]);
  const d = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const color =
    tone === "ok"
      ? "var(--a1-ok)"
      : tone === "warn"
        ? "var(--a1-warn)"
        : tone === "bad"
          ? "var(--a1-bad)"
          : tone === "brand"
            ? "var(--a1-brand)"
            : "var(--a1-ink-2)";
  const id = `sp-${tone}-${width}-${height}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.3" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={`${d} L${width - 1},${height} L1,${height} Z`} fill={`url(#${id})`} />}
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
      />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.2" fill={color} />
    </svg>
  );
}

/** Right-hand slide-over. The list stays visible behind it. */
export function SlideOver({
  open,
  onClose,
  title,
  sub,
  children,
  width = 640,
  footer,
  header,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  sub?: ReactNode;
  children: ReactNode;
  width?: number;
  footer?: ReactNode;
  header?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-40"
            style={{ background: "rgba(5,5,6,0.55)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={onClose}
          />
          <motion.aside
            key="panel"
            className="a1-pop fixed right-3 top-3 bottom-3 z-50 flex flex-col overflow-hidden"
            style={{ width: `min(${width}px, calc(100vw - 24px))`, borderRadius: 16 }}
            initial={{ transform: "translateX(24px)", opacity: 0 }}
            animate={{ transform: "translateX(0px)", opacity: 1, transition: { duration: 0.22, ease: [0.32, 0.72, 0, 1] } }}
            exit={{ transform: "translateX(24px)", opacity: 0, transition: { duration: 0.12, ease: [0.23, 1, 0.32, 1] } }}
            role="dialog"
            aria-modal
          >
            {header ?? (
              <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
                <div className="min-w-0">
                  <div className="a1-h2 a1-truncate">{title}</div>
                  {sub && <div className="a1-faint mt-0.5 text-[12px]">{sub}</div>}
                </div>
                <button className="a1-iconbtn" onClick={onClose} aria-label="Close">
                  <X size={16} />
                </button>
              </div>
            )}
            <div className="a1-scroll min-h-0 flex-1" style={{ overscrollBehavior: "contain" }}>{children}</div>
            {footer && <div className="border-t px-5 py-3">{footer}</div>}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

/** Simple hover tooltip. */
export function Tip({ label, children, side = "top" }: { label: ReactNode; children: ReactNode; side?: "top" | "bottom" }) {
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const show = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), 220);
  };
  const hide = () => {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(false);
  };
  return (
    <span className="relative inline-flex" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} tabIndex={0}>
      {children}
      <AnimatePresence>
        {open && (
          <motion.span
            className="a1-pop pointer-events-none absolute left-1/2 z-50 w-max max-w-[260px] px-2.5 py-1.5 text-[11.5px] leading-snug"
            style={{ [side === "top" ? "bottom" : "top"]: "calc(100% + 6px)", borderRadius: 8, transformOrigin: side === "top" ? "bottom center" : "top center" }}
            initial={{ opacity: 0, x: "-50%", scale: 0.97 }}
            animate={{ opacity: 1, x: "-50%", scale: 1 }}
            transition={{ duration: 0.12, ease: [0.23, 1, 0.32, 1] }}
          >
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
