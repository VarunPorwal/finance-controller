import type { Metadata } from "next";
import "./app.css";
import "./finco-tokens.css";
import "./finco-theme-light.css";
import { Shell } from "./_components/shell/shell";
import { ThemeProvider } from "./_components/shell/theme";

export const metadata: Metadata = {
  title: "Finco",
  description: "Reconciles what it can prove, refuses what it cannot, and hands you the rest.",
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <Shell>{children}</Shell>
    </ThemeProvider>
  );
}
