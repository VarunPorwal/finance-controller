"use client";

import { useEffect } from "react";

/**
 * Drives the cursor-tracked spotlight on .m-card/.m-frame (marketing.css)
 * with one delegated listener instead of a handler per card. Sets --mx/--my
 * on whichever card is under the pointer; CSS does the rest.
 */
export function CardSpotlight() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    function onMove(e: MouseEvent) {
      const target = (e.target as HTMLElement).closest<HTMLElement>(".m-card, .m-frame");
      if (!target) return;
      const rect = target.getBoundingClientRect();
      target.style.setProperty("--mx", `${e.clientX - rect.left}px`);
      target.style.setProperty("--my", `${e.clientY - rect.top}px`);
    }
    document.addEventListener("mousemove", onMove, { passive: true });
    return () => document.removeEventListener("mousemove", onMove);
  }, []);

  return null;
}
