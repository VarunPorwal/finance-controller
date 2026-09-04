"use client";

import type { ReactNode } from "react";
import { MotionConfig } from "framer-motion";
import { ShellProvider } from "./shell-context";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";
import { Assistant } from "./assistant";
import { CommandPalette } from "./palette";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <ShellProvider>
      <MotionConfig reducedMotion="user">
      <div className="flex h-screen w-full overflow-hidden">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <div className="flex min-h-0 flex-1">
            <main className="a1-scroll min-w-0 flex-1">{children}</main>
          </div>
        </div>
      </div>
      <Assistant />
      <CommandPalette />
      </MotionConfig>
    </ShellProvider>
  );
}
