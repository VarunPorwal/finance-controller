import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { RunProvider } from "@/lib/run-context";
import { QueryProvider } from "@/lib/query-client";

// Geist for every UI string, Geist Mono for every rupee figure, UTR, rule id
// and count. Tabular figures are applied by the `.num` utility.
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Finco, the AI finance controller",
  description:
    "Reconciles Razorpay settlements, bank statements and Tally ledgers. Resolves what it can prove, refuses to close what it cannot.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="antialiased">
        <QueryProvider>
          <RunProvider>{children}</RunProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
