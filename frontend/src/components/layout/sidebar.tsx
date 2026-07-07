"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Globe, Zap, ShoppingCart, TrendingUp,
  Shield, DollarSign, Briefcase, Server, BarChart2,
  Activity, FileText, Settings, LineChart, Target,
  CandlestickChart, Sparkles, Bot, FlaskConical, Filter, Brain,
  PieChart, BookOpen, Microscope, MonitorDot, CalendarDays, ShieldCheck,
  ClipboardList, TestTube2, TrendingDown, ChevronDown, ChevronRight,
  GitBranch, Sliders, Shuffle, Map, Trophy, AlertTriangle, Rocket,
  Cpu, BarChart, Layers, Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { APP_NAME } from "@/lib/constants";

const ICON_MAP = {
  LayoutDashboard, Globe, Zap, ShoppingCart, TrendingUp,
  Shield, DollarSign, Briefcase, Server, BarChart2,
  Activity, FileText, Settings, LineChart, Target,
  CandlestickChart, Sparkles, Bot, FlaskConical, Filter, Brain,
  PieChart, BookOpen, Microscope, MonitorDot, CalendarDays, ShieldCheck,
  ClipboardList, TestTube2, TrendingDown,
  GitBranch, Sliders, Shuffle, Map, Trophy, AlertTriangle, Rocket,
  Cpu, BarChart, Layers, Search,
} as const;

type NavItem = { label: string; href: string; icon: keyof typeof ICON_MAP };
type NavGroup = { title: string; icon: keyof typeof ICON_MAP; items: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
  {
    title: "Trading",
    icon: "Zap",
    items: [
      { label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" },
      { label: "Signals", href: "/signals", icon: "Zap" },
      { label: "Orders", href: "/orders", icon: "ShoppingCart" },
      { label: "Positions", href: "/positions", icon: "TrendingUp" },
      { label: "Risk", href: "/risk", icon: "Shield" },
      { label: "Capital", href: "/capital", icon: "DollarSign" },
      { label: "Trade Mgmt", href: "/trade-management", icon: "TrendingDown" },
    ],
  },
  {
    title: "Market",
    icon: "BarChart",
    items: [
      { label: "Market Overview", href: "/market-overview", icon: "LineChart" },
      { label: "Option Chain", href: "/option-chain", icon: "CandlestickChart" },
      { label: "Opportunities", href: "/opportunities", icon: "Target" },
      { label: "Universe", href: "/universe", icon: "Globe" },
    ],
  },
  {
    title: "Analytics",
    icon: "BarChart2",
    items: [
      { label: "Analytics", href: "/analytics", icon: "BarChart2" },
      { label: "Signal Analytics", href: "/signal-analytics", icon: "FlaskConical" },
      { label: "Strategy Analytics", href: "/strategy-analytics", icon: "BarChart2" },
      { label: "Filter Analytics", href: "/filter-analytics", icon: "Filter" },
      { label: "Signal Intelligence", href: "/signal-intelligence", icon: "Brain" },
      { label: "Portfolio Intel", href: "/portfolio-intelligence", icon: "PieChart" },
      { label: "Post-Trade", href: "/post-trade", icon: "BookOpen" },
      { label: "Weekly Report", href: "/weekly-report", icon: "CalendarDays" },
    ],
  },
  {
    title: "Research",
    icon: "Microscope",
    items: [
      { label: "Research Hub", href: "/research-hub", icon: "Microscope" },
      { label: "Strategy Versions", href: "/strategy-versions", icon: "GitBranch" },
      { label: "Param Optimization", href: "/parameter-optimization", icon: "Sliders" },
      { label: "Walk-Forward", href: "/walk-forward", icon: "LineChart" },
      { label: "Monte Carlo", href: "/monte-carlo", icon: "Shuffle" },
      { label: "Regime Performance", href: "/regime-performance", icon: "Map" },
      { label: "Symbol Rankings", href: "/symbol-rankings", icon: "Trophy" },
      { label: "False Positive", href: "/false-positive", icon: "AlertTriangle" },
      { label: "Promotion Queue", href: "/strategy-promotion", icon: "Rocket" },
      { label: "Research (Legacy)", href: "/research", icon: "Search" },
    ],
  },
  {
    title: "Intelligence",
    icon: "Sparkles",
    items: [
      { label: "AI Insights", href: "/ai-insights", icon: "Sparkles" },
      { label: "Backtest", href: "/backtest", icon: "BarChart2" },
      { label: "Experiments", href: "/experiments", icon: "TestTube2" },
      { label: "Validation", href: "/validation", icon: "ShieldCheck" },
    ],
  },
  {
    title: "Operations",
    icon: "Cpu",
    items: [
      { label: "Portfolios", href: "/portfolios", icon: "Briefcase" },
      { label: "Broker", href: "/broker", icon: "Server" },
      { label: "Paper Trading", href: "/paper-trading", icon: "FileText" },
      { label: "Paper Daemon", href: "/paper-daemon", icon: "Bot" },
      { label: "Operations", href: "/operations", icon: "ClipboardList" },
      { label: "Operator", href: "/operator", icon: "MonitorDot" },
    ],
  },
  {
    title: "System",
    icon: "Layers",
    items: [
      { label: "System Health", href: "/system-health", icon: "Activity" },
      { label: "Settings", href: "/settings", icon: "Settings" },
    ],
  },
];

function NavGroup({
  group,
  pathname,
}: {
  group: NavGroup;
  pathname: string;
}) {
  const hasActive = group.items.some(
    (item) => pathname === item.href || pathname.startsWith(item.href + "/")
  );
  const [open, setOpen] = useState(hasActive);
  const GroupIcon = ICON_MAP[group.icon];

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "w-full flex items-center justify-between px-3 py-2 rounded-md text-xs font-semibold uppercase tracking-wider transition-colors",
          hasActive
            ? "text-sidebar-accent-foreground"
            : "text-sidebar-foreground/50 hover:text-sidebar-foreground"
        )}
      >
        <div className="flex items-center gap-2">
          <GroupIcon className="h-3.5 w-3.5 shrink-0" />
          {group.title}
        </div>
        {open
          ? <ChevronDown className="h-3 w-3" />
          : <ChevronRight className="h-3 w-3" />}
      </button>

      {open && (
        <div className="ml-2 pl-2 border-l border-sidebar-border mb-1">
          {group.items.map((item) => {
            const Icon = ICON_MAP[item.icon];
            const active =
              pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
                )}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 border-r bg-sidebar flex flex-col shrink-0">
      <div className="h-14 flex items-center px-4 border-b shrink-0">
        <span className="font-semibold text-sm tracking-tight text-sidebar-foreground">
          {APP_NAME}
        </span>
      </div>
      <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {NAV_GROUPS.map((group) => (
          <NavGroup key={group.title} group={group} pathname={pathname} />
        ))}
      </nav>
    </aside>
  );
}
