"use client";

import type { ReactNode } from "react";
import { MotionConfig } from "framer-motion";
import { ShellProvider, useShell } from "./shell-context";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";
import { Assistant } from "./assistant";
import { CommandPalette } from "./palette";

function ShellBody({ children }: { children: ReactNode }) {
  const { sidebarOpen, setSidebarOpen } = useShell();
  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Below md, the sidebar becomes an off-canvas drawer over a scrim
          instead of squeezing a 286px rail into a phone-width viewport. */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setSidebarOpen(false)} aria-hidden />
      )}
      <div className={`app-sidebar-drawer${sidebarOpen ? " is-open" : ""}`}>
        <Sidebar onNavigate={() => setSidebarOpen(false)} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <div className="flex min-h-0 flex-1">
          <main className="app-scroll min-w-0 flex-1">{children}</main>
        </div>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <ShellProvider>
      <MotionConfig reducedMotion="user">
        <ShellBody>{children}</ShellBody>
        <Assistant />
        <CommandPalette />
      </MotionConfig>
    </ShellProvider>
  );
}
