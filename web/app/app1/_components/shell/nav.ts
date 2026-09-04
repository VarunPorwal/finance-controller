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
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  question: string;
  icon: LucideIcon;
}

export const DAILY: NavItem[] = [
  { href: "/app1", label: "Overview", question: "Is my money under control?", icon: LayoutDashboard },
  { href: "/app1/run", label: "Run", question: "Did it read my evidence correctly?", icon: Play },
  { href: "/app1/decisions", label: "Decisions", question: "Where is my money unexplained?", icon: Gavel },
  { href: "/app1/settlements", label: "Settlements", question: "What did each settlement actually do?", icon: ArrowLeftRight },
  { href: "/app1/reconcile", label: "Reconcile", question: "Do bank and books actually agree?", icon: Scale },
  { href: "/app1/cash", label: "Cash", question: "Where is my money, and will I have enough?", icon: Wallet },
  { href: "/app1/rules", label: "Rule Book", question: "Why did Finco calculate this amount this way?", icon: BookOpen },
];

export const EVIDENCE: NavItem[] = [
  { href: "/app1/controller-activity", label: "Controller Activity", question: "What did the engine do, and would it do it again?", icon: Activity },
  { href: "/app1/audit", label: "Audit Trail", question: "Can I prove what happened?", icon: ShieldCheck },
  { href: "/app1/evaluation", label: "Evaluation", question: "How accurate is it, measured?", icon: Target },
  { href: "/app1/records", label: "Records", question: "Show me the underlying evidence.", icon: Database },
];

export const SETTINGS: NavItem = { href: "/app1/settings", label: "Settings", question: "", icon: Settings };

export const ALL_NAV = [...DAILY, ...EVIDENCE, SETTINGS];

export function activeNav(pathname: string): NavItem | undefined {
  if (pathname === "/app1" || pathname === "/app1/") return DAILY[0];
  return ALL_NAV.filter((n) => n.href !== "/app1").find((n) => pathname.startsWith(n.href));
}
