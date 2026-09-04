"use client";

// Theme state for the Finco design system. Persisted via a plain cookie —
// CLAUDE.md forbids localStorage/sessionStorage in the frontend, but says
// nothing about cookies, so the choice survives a reload without breaking
// that rule.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type Theme = "dark" | "light";

const COOKIE_KEY = "fc_theme";

function readThemeCookie(): Theme {
  if (typeof document === "undefined") return "dark";
  const match = document.cookie.match(/(?:^|;\s*)fc_theme=(dark|light)(?:;|$)/);
  return match ? (match[1] as Theme) : "dark";
}

function writeThemeCookie(theme: Theme) {
  document.cookie = `${COOKIE_KEY}=${theme}; path=/; max-age=31536000; SameSite=Lax`;
}

interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

const Ctx = createContext<ThemeState | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readThemeCookie);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      writeThemeCookie(next);
      return next;
    });
  }, []);
  const value = useMemo(() => ({ theme, toggle }), [theme, toggle]);
  return (
    // "a1" stays alongside "fc" until every page is converted off the old
    // theme — app1.css scopes every a1- class under a ".a1" ancestor, and
    // dropping it here would silently unstyle whatever hasn't moved yet.
    <div className="fc a1" data-theme={theme} suppressHydrationWarning style={{ minHeight: "100vh" }}>
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
