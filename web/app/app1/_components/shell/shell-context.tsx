"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

interface ShellState {
  assistantOpen: boolean;
  openAssistant: (prefill?: string) => void;
  closeAssistant: () => void;
  assistantPrefill: string;
  paletteOpen: boolean;
  setPaletteOpen: (v: boolean) => void;
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
}

const Ctx = createContext<ShellState | null>(null);

export function ShellProvider({ children }: { children: ReactNode }) {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantPrefill, setPrefill] = useState("");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const openAssistant = useCallback((prefill = "") => {
    setPrefill(prefill);
    setAssistantOpen(true);
  }, []);
  const closeAssistant = useCallback(() => setAssistantOpen(false), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      if (mod && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setAssistantOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo(
    () => ({ assistantOpen, openAssistant, closeAssistant, assistantPrefill, paletteOpen, setPaletteOpen, sidebarOpen, setSidebarOpen }),
    [assistantOpen, openAssistant, closeAssistant, assistantPrefill, paletteOpen, sidebarOpen],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useShell(): ShellState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useShell must be used inside <ShellProvider>");
  return ctx;
}
