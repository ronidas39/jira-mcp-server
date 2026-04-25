"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Briefcase,
  Folder,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Plus,
  Settings,
  Menu,
} from "lucide-react";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const items: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/issues", label: "Issues", icon: ListChecks },
  { href: "/issues/new", label: "New issue", icon: Plus },
  { href: "/projects", label: "Projects", icon: Folder },
  { href: "/sprints", label: "Sprints", icon: Briefcase },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/settings", label: "Settings", icon: Settings },
];

function NavList({ pathname, onClick }: { pathname: string; onClick?: () => void }): React.ReactElement {
  return (
    <nav className="flex flex-col gap-1 p-2">
      {items.map((item) => {
        const Icon = item.icon;
        const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onClick}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function AppSidebar(): React.ReactElement {
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <aside className="hidden w-64 shrink-0 border-r bg-card md:flex md:flex-col">
        <div className="flex h-14 items-center justify-between gap-2 px-4 font-semibold">
          <span>Jira MCP</span>
          <ThemeToggle />
        </div>
        <Separator />
        <NavList pathname={pathname} />
      </aside>
      <header className="sticky top-0 z-30 flex h-14 w-full items-center gap-2 border-b bg-background px-4 md:hidden">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Open menu">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <div className="flex h-14 items-center justify-between px-4 font-semibold">
              <span>Jira MCP</span>
              <ThemeToggle />
            </div>
            <Separator />
            <NavList pathname={pathname} onClick={() => setOpen(false)} />
          </SheetContent>
        </Sheet>
        <span className="font-semibold">Jira MCP</span>
      </header>
    </>
  );
}
