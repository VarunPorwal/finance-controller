"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

export type Run = { text: string; className?: string };

/**
 * Types a list of styled runs out character by character, once, the first
 * time it scrolls into view — so the bridge reads as a live terminal
 * producing the number, not a static printout that just fades in. Retypes
 * whenever `runs` changes (a new run of the reconciliation).
 */
export function TypedTree({ runs, className }: { runs: Run[]; className?: string }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLPreElement>(null);
  const [started, setStarted] = useState(false);
  const total = runs.reduce((n, r) => n + r.text.length, 0);
  const [count, setCount] = useState(reduce ? total : 0);

  useEffect(() => {
    if (reduce || !ref.current) return;
    const el = ref.current;
    const isOnScreen = () => {
      const r = el.getBoundingClientRect();
      return r.top < window.innerHeight - 100 && r.bottom > 100;
    };
    // The bridge data (and so this component) can mount after the user has
    // already scrolled to it, in which case it's on-screen from its very
    // first frame and there is no "enters the viewport" event left to wait
    // for. Check synchronously at mount, then again on scroll — don't rely
    // on IntersectionObserver alone, since its first callback isn't
    // guaranteed to land promptly on every host.
    if (isOnScreen()) {
      setStarted(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) finish();
      },
      { rootMargin: "-100px" },
    );
    io.observe(el);
    const onScroll = () => {
      if (isOnScreen()) finish();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    function finish() {
      setStarted(true);
      io.disconnect();
      window.removeEventListener("scroll", onScroll);
    }
    return () => {
      io.disconnect();
      window.removeEventListener("scroll", onScroll);
    };
  }, [reduce]);

  useEffect(() => {
    if (reduce) {
      setCount(total);
      return;
    }
    if (!started) return;
    setCount(0);
    const perTick = Math.max(1, Math.round(total / 90));
    const id = setInterval(() => {
      setCount((c) => {
        const next = c + perTick;
        if (next >= total) {
          clearInterval(id);
          return total;
        }
        return next;
      });
    }, 16);
    return () => clearInterval(id);
  }, [started, total, reduce]);

  let remaining = count;
  const nodes: React.ReactNode[] = [];
  runs.forEach((r, i) => {
    if (remaining <= 0 || !r.text) return;
    const slice = r.text.slice(0, remaining);
    remaining -= r.text.length;
    if (!slice) return;
    nodes.push(
      <span key={i} className={r.className}>
        {slice}
      </span>,
    );
  });

  return (
    <pre ref={ref} className={cn("tree", className)}>
      {nodes}
      {started && count < total && <span className="type-cursor">▍</span>}
    </pre>
  );
}
