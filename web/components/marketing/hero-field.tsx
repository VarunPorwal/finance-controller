"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

// ThreeUI's Predictive Arc family, "signal-particles": a dark field of
// points with soft connective pulses. Lazy, client-only, behind a poster.
// It is the whole thesis drawn as a background: three sources, pulses
// connecting them.
const PredictiveArcCanvas = dynamic(
  () => import("@designcodeio/threeui/components/PredictiveArcCanvas").then((m) => m.PredictiveArcCanvas),
  { ssr: false, loading: () => null },
);

export function HeroField() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    if (!reduced && gl) setReady(true);
  }, []);

  return (
    <div className="absolute inset-0 overflow-hidden" aria-hidden>
      <div className="m-poster absolute inset-0" />
      {ready && (
        <div className="absolute inset-0" style={{ width: "100%", height: "100%" }}>
          <PredictiveArcCanvas variant="signal-particles" mode="dark" speed={1} brightness={1.35} saturation={1.1} style={{ width: "100%", height: "100%" }} />
        </div>
      )}
      <div className="m-hero-fade absolute inset-0" />
    </div>
  );
}
