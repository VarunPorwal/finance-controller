"use client";

import { useState, type ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * A frame that settles into place the first time it scrolls into view.
 * 28px of travel over a slow, strong ease-out, once, so the motion actually
 * reads instead of resolving before the eye catches it.
 *
 * When a child list uses the `.cascade` utility (marketing.css) for its own
 * per-item stagger, this also flips the shared `in-view` class the moment it
 * enters the viewport, so that CSS-driven stagger starts at the same beat as
 * the reveal itself instead of firing on mount.
 */
export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduce = useReducedMotion();
  const [inView, setInView] = useState(!!reduce);
  return (
    <motion.div
      className={inView ? `${className ?? ""} in-view` : className}
      initial={reduce ? false : { opacity: 0, y: 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-100px" }}
      transition={{ duration: 0.9, ease: EASE, delay }}
      onViewportEnter={() => setInView(true)}
    >
      {children}
    </motion.div>
  );
}
