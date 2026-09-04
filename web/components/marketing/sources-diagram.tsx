/**
 * Three sources into one cascade, out to three outcomes. Pure SVG; the
 * pulses are CSS dash animations. No WebGL on this element.
 */
export function SourcesDiagram() {
  const sources = [
    { y: 50, label: "Razorpay", sub: "settlements · fees · GST · TDS", color: "var(--src-razorpay)" },
    { y: 140, label: "Bank", sub: "the only proof money moved", color: "var(--src-bank)" },
    { y: 230, label: "Tally", sub: "what the books expected", color: "var(--src-ledger)" },
  ];
  const outcomes = [
    { y: 50, label: "Auto-resolved", sub: "evidence attached, every leg", color: "var(--ok)" },
    { y: 140, label: "Needs you", sub: "ranked, with consequence and deadline", color: "var(--warn)" },
    { y: 230, label: "Unexplained", sub: "never guessed, never closed", color: "var(--bad)" },
  ];
  const cx = 400;
  const cy = 140;

  return (
    <svg viewBox="0 0 880 280" className="h-auto w-full" role="img" aria-label="Three sources feed a five-stage cascade that produces auto-resolved matches, a queue for humans, and an explicit unexplained residual.">
      {sources.map((s) => (
        <g key={s.label}>
          <path d={`M170 ${s.y} C 260 ${s.y}, 280 ${cy}, ${cx - 78} ${cy}`} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="1.5" />
          <path d={`M170 ${s.y} C 260 ${s.y}, 280 ${cy}, ${cx - 78} ${cy}`} fill="none" stroke={s.color} strokeWidth="1.5" className="m-pulse" opacity="0.9" />
          <circle cx="160" cy={s.y} r="5" fill={s.color} className="m-node-glow" style={{ color: s.color }} />
          <text x="145" y={s.y + 4} textAnchor="end" fill="#eef1f6" fontSize="14" fontWeight="600" fontFamily="var(--font-geist-sans)">
            {s.label}
          </text>
          <text x="145" y={s.y + 20} textAnchor="end" fill="#6d7686" fontSize="11" fontFamily="var(--font-geist-sans)">
            {s.sub}
          </text>
        </g>
      ))}

      <rect x={cx - 78} y={cy - 56} width="156" height="116" rx="14" fill="rgba(10,12,18,0.9)" stroke="rgba(255,255,255,0.12)" />
      <text x={cx} y={cy - 32} textAnchor="middle" fill="#6d7686" fontSize="10" letterSpacing="1.5" fontFamily="var(--font-geist-mono)">
        CASCADE
      </text>
      {["exact ref", "fee-adjusted", "date-shift", "subset-sum", "fuzzy · never auto"].map((s, i) => (
        <text key={s} x={cx} y={cy - 14 + i * 13} textAnchor="middle" fill={i === 4 ? "#f5a524" : "#aab2c0"} fontSize="9.5" fontFamily="var(--font-geist-mono)">
          {i + 1} {s}
        </text>
      ))}

      {outcomes.map((o) => (
        <g key={o.label}>
          <path d={`M${cx + 78} ${cy} C 540 ${cy}, 560 ${o.y}, 630 ${o.y}`} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="1.5" />
          <path d={`M${cx + 78} ${cy} C 540 ${cy}, 560 ${o.y}, 630 ${o.y}`} fill="none" stroke={o.color} strokeWidth="1.5" className="m-pulse" opacity="0.9" />
          <circle cx="640" cy={o.y} r="5" fill={o.color} className="m-node-glow" style={{ color: o.color }} />
          <text x="655" y={o.y + 4} fill="#eef1f6" fontSize="14" fontWeight="600" fontFamily="var(--font-geist-sans)">
            {o.label}
          </text>
          <text x="655" y={o.y + 20} fill="#6d7686" fontSize="11" fontFamily="var(--font-geist-sans)">
            {o.sub}
          </text>
        </g>
      ))}
    </svg>
  );
}
