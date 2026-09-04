import {
  Activity,
  ArrowLeftRight,
  BookOpen,
  Compass,
  Landmark,
  LayoutDashboard,
  ShieldCheck,
  Table2,
  TriangleAlert,
  Upload,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Which summary count, if any, sits beside the label. */
  badge?: "needs_you";
  hint?: string;
}

export const NAV_PRIMARY: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard, hint: "The books at a glance" },
  { href: "/ingest", label: "Ingest", icon: Upload, hint: "Bring in Razorpay, bank and Tally files" },
  { href: "/exceptions", label: "Exceptions", icon: TriangleAlert, badge: "needs_you", hint: "The decisions only you can make" },
  { href: "/reconcile", label: "Reconcile", icon: ArrowLeftRight, hint: "Gross to bank, line by line" },
  { href: "/cash", label: "Cash", icon: Landmark, hint: "What is at risk, held, or claimable" },
  { href: "/rules", label: "Rule Book", icon: BookOpen, hint: "Deduction policy, versioned" },
];

export const NAV_SECONDARY: NavItem[] = [
  { href: "/activity", label: "Controller Activity", icon: Activity, hint: "What the agent did, and why" },
  { href: "/audit", label: "Audit Trail", icon: ShieldCheck, hint: "Every decision, hash-chained" },
  { href: "/records", label: "Records", icon: Table2, hint: "Normalised rows from every source" },
  { href: "/guide", label: "Guide", icon: Compass, hint: "What this is and how to walk through it" },
];

/** Reachable from the command bar and in-page links, not the sidebar. */
export const NAV_HIDDEN: { href: string; label: string; hint: string }[] = [
  { href: "/eval", label: "Evaluation", hint: "Precision, recall and the quality gates" },
  { href: "/ask", label: "Ask the books", hint: "Aggregates, breakdowns, diffs, what-ifs" },
  { href: "/landing", label: "Product page", hint: "The pitch, with live numbers" },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}
