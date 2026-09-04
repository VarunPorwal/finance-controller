"use client";

// Theme state for the Finco design system. In-memory only — CLAUDE.md
// forbids localStorage/sessionStorage in the frontend, so the choice does not
// survive a reload; it always starts dark.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type Theme = "dark" | "light";

interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

const Ctx = createContext<ThemeState | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");
  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  const value = useMemo(() => ({ theme, toggle }), [theme, toggle]);
  return (
    // "a1" stays alongside "fc" until every page is converted off the old
    // theme — app1.css scopes every a1- class under a ".a1" ancestor, and
    // dropping it here would silently unstyle whatever hasn't moved yet.
    <div className="fc a1" data-theme={theme} style={{ minHeight: "100vh" }}>
      <div className="fc-bloom-layer" aria-hidden="true" />
      <Ctx.Provider value={value}>{children}</Ctx.Provider>
    </div>
  );
}

export function useTheme(): ThemeState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
