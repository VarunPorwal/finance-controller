"use client";

import { useEffect, useRef, useState } from "react";
import { animate, useReducedMotion } from "framer-motion";

/**
 * A figure that counts to its value on arrival and tweens between values
 * afterwards. Presentation only: the value is server-computed; this only
 * chooses which intermediate frames to draw on the way there. 500ms so the
 * eye is drawn to the number we want read, then it holds still.
 */
export function AnimatedNumber({
  value,
  format = (n) => String(Math.round(n)),
  duration = 0.5,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
}) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);
  const from = useRef(0);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      from.current = value;
      return;
    }
    const controls = animate(from.current, value, {
      duration,
      ease: [0.23, 1, 0.32, 1],
      onUpdate: (v) => setDisplay(v),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, duration, reduce]);

  return <>{format(display)}</>;
}
