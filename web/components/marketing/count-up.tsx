"use client";

import { useEffect, useRef, useState } from "react";
import { animate, useReducedMotion } from "framer-motion";

/**
 * Counts up from its previous value to the next real figure from the API.
 * Never invents a number: while the value is unknown it renders "—".
 */
export function CountUp({ value, format, duration = 1.2 }: { value: number | null | undefined; format: (n: number) => string; duration?: number }) {
  const [display, setDisplay] = useState(value ?? 0);
  const prev = useRef(0);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (value == null) return;
    if (reduce) {
      setDisplay(value);
      prev.current = value;
      return;
    }
    const controls = animate(prev.current, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
      onComplete: () => {
        prev.current = value;
      },
    });
    return () => controls.stop();
  }, [value, duration, reduce]);

  if (value == null) return <>—</>;
  return <>{format(display)}</>;
}
