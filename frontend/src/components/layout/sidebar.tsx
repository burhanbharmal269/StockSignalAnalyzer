"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Globe, Zap, ShoppingCart, TrendingUp,
  Shield, DollarSign, Briefcase, Server, BarChart2,
  Activity, FileText, Settings, LineChart, Target,
  CandlestickChart, Sparkles, Bot, Newspaper, FlaskConical, Filter, Brain,
  PieChart, BookOpen, Microscope, MonitorDot, CalendarDays,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { APP_NAME } from "@/lib/constants";

const ICON_MAP = {
  LayoutDashboard, Globe, Zap, ShoppingCart, TrendingUp,
  Shield, DollarSign, Briefcase, Server, BarChart2,
  Activity, FileText, Settings, LineChart, Target,
  CandlestickChart, Sparkles, Bot, Newspaper, FlaskConical, Filter, Brain,
  PieChart, BookOpen, Microscope, MonitorDot, CalendarDays,
} as const;

const NAV_ITEMS = [
  { label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" },
  { label: "Universe", href: "/universe", icon: "Globe" },
  { label: "Signals", href: "/signals", icon: "Zap" },
  { label: "Orders", href: "/orders", icon: "ShoppingCart" },
  { label: "Positions", href: "/positions", icon: "TrendingUp" },
  { label: "Risk", href: "/risk", icon: "Shield" },
  { label: "Capital", href: "/capital", icon: "DollarSign" },
  { label: "Portfolios", href: "/portfolios", icon: "Briefcase" },
  { label: "Broker", href: "/broker", icon: "Server" },
  { label: "Analytics", href: "/analytics", icon: "BarChart2" },
  { label: "System Health", href: "/system-health", icon: "Activity" },
  { label: "Paper Trading", href: "/paper-trading", icon: "FileText" },
  { label: "Settings", href: "/settings", icon: "Settings" },
  { label: "Market Overview", href: "/market-overview", icon: "LineChart" },
  { label: "Opportunities", href: "/opportunities", icon: "Target" },
  { label: "Option Chain", href: "/option-chain", icon: "CandlestickChart" },
  { label: "Backtest", href: "/backtest", icon: "BarChart2" },
  { label: "AI Insights", href: "/ai-insights", icon: "Sparkles" },
  { label: "Paper Daemon", href: "/paper-daemon", icon: "Bot" },
  { label: "Signal Analytics", href: "/signal-analytics", icon: "FlaskConical" },
  { label: "Strategy Analytics", href: "/strategy-analytics", icon: "BarChart2" },
  { label: "Filter Analytics", href: "/filter-analytics", icon: "Filter" },
  { label: "Signal Intelligence", href: "/signal-intelligence", icon: "Brain" },
  { label: "Portfolio Intel", href: "/portfolio-intelligence", icon: "PieChart" },
  { label: "Post-Trade", href: "/post-trade", icon: "BookOpen" },
  { label: "Research", href: "/research", icon: "Microscope" },
  { label: "Operator", href: "/operator", icon: "MonitorDot" },
  { label: "Weekly Report", href: "/weekly-report", icon: "CalendarDays" },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 border-r bg-sidebar flex flex-col shrink-0">
      <div className="h-14 flex items-center px-4 border-b shrink-0">
        <span className="font-semibold text-sm tracking-tight text-sidebar-foreground">
          {APP_NAME}
        </span>
      </div>
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {NAV_ITEMS.map((item) => {
          const Icon = ICON_MAP[item.icon as keyof typeof ICON_MAP];
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
