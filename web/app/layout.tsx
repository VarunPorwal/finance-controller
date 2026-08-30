import type { Metadata } from "next";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// PRD §13.3: Satoshi (display), Inter (body), IBM Plex Mono (every number,
// reference and UTR). Satoshi is not on Google Fonts — it ships from
// Fontshare, loaded below via <link> with a system-sans fallback baked into
// --font-satoshi so a cold cache (or `make demo-local`'s no-network path)
// degrades to a normal heading font instead of an invisible one.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Finance Controller",
  description: "Reconciles Razorpay settlements, bank statements and Tally ledger exports.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${plexMono.variable}`}>
      <head>
        <link
          href="https://api.fontshare.com/v2/css?f[]=satoshi@500,700,900&display=swap"
          rel="stylesheet"
        />
        <style>{`:root { --font-satoshi: 'Satoshi', var(--font-inter), sans-serif; }`}</style>
      </head>
      <body className="antialiased">{children}</body>
    </html>
  );
}
