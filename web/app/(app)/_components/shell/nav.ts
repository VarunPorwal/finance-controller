import type { LucideIcon } from "lucide-react";
import {
  LayoutDashboard,
  Play,
  Gavel,
  ArrowLeftRight,
  Scale,
  Wallet,
  BookOpen,
  Activity,
  ShieldCheck,
  Target,
  Database,
  Settings,
  Compass,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  question: string;
  icon: LucideIcon;
}

export const DAILY: NavItem[] = [
  { href: "/", label: "Overview", question: "Is my money under control?", icon: LayoutDashboard },
  { href: "/run", label: "Run", question: "Did it read my evidence correctly?", icon: Play },
  { href: "/decisions", label: "Decisions", question: "Where is my money unexplained?", icon: Gavel },
  { href: "/settlements", label: "Settlements", question: "What did each settlement actually do?", icon: ArrowLeftRight },
  { href: "/reconcile", label: "Reconcile", question: "Do bank and books actually agree?", icon: Scale },
  { href: "/cash", label: "Cash", question: "Where is my money, and will I have enough?", icon: Wallet },
  { href: "/rules", label: "Rule Book", question: "Why did Finco calculate this amount this way?", icon: BookOpen },
];

export const EVIDENCE: NavItem[] = [
  { href: "/controller-activity", label: "Controller Activity", question: "What did the engine do, and would it do it again?", icon: Activity },
  { href: "/audit", label: "Audit Trail", question: "Can I prove what happened?", icon: ShieldCheck },
  { href: "/evaluation", label: "Evaluation", question: "How accurate is it, measured?", icon: Target },
  { href: "/records", label: "Records", question: "Show me the underlying evidence.", icon: Database },
  { href: "/guide", label: "Guide", question: "What is this, and how do I use it?", icon: Compass },
];

export const SETTINGS: NavItem = { href: "/settings", label: "Settings", question: "", icon: Settings };

export const ALL_NAV = [...DAILY, ...EVIDENCE, SETTINGS];

export function activeNav(pathname: string): NavItem | undefined {
  if (pathname === "/" || pathname === "/") return DAILY[0];
  return ALL_NAV.filter((n) => n.href !== "/").find((n) => pathname.startsWith(n.href));
}
