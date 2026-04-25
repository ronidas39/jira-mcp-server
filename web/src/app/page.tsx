import Link from "next/link";
import { Activity, Folder, ListChecks } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { callTool } from "@/lib/mcp-client";
import { toIssueRow } from "@/lib/jira";
import { formatRelativeDate } from "@/lib/utils";
import { publicConfig } from "@/lib/env";

export const dynamic = "force-dynamic";

interface ProjectsResult {
  projects: Array<{ key: string; name: string }>;
}

interface StatusBucketsResult {
  buckets: Array<{ status: string; count: number }>;
}

interface WorkloadResult {
  entries: Array<{ assignee: { display_name?: string } | null; open_issues: number }>;
}

interface SearchIssuesResult {
  issues: Array<unknown>;
  total: number;
}

async function safeCall<T>(name: string, args: Record<string, unknown>, fallback: T): Promise<T> {
  try {
    return (await callTool(name, args)) as T;
  } catch {
    return fallback;
  }
}

export default async function DashboardPage(): Promise<React.ReactElement> {
  const projectsData = await safeCall<ProjectsResult>("list_projects", {}, { projects: [] });
  const firstProject = projectsData.projects[0];
  const projectKey = firstProject?.key ?? "";

  const [statusData, workloadData, recentData] = await Promise.all([
    projectKey
      ? safeCall<StatusBucketsResult>("issues_by_status", { project_key: projectKey }, { buckets: [] })
      : Promise.resolve({ buckets: [] } as StatusBucketsResult),
    projectKey
      ? safeCall<WorkloadResult>("workload_by_assignee", { project_key: projectKey }, { entries: [] })
      : Promise.resolve({ entries: [] } as WorkloadResult),
    safeCall<SearchIssuesResult>(
      "search_issues",
      { jql: "updated >= -2d ORDER BY updated DESC", max_results: 10 },
      { issues: [], total: 0 },
    ),
  ]);

  const totalIssues = statusData.buckets.reduce((sum, b) => sum + b.count, 0);
  const topWorkload = workloadData.entries.slice(0, 5);
  const recentRows = recentData.issues.map(toIssueRow);
  const config = publicConfig();

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          {projectKey ? (
            <>Showing data for project <span className="font-medium">{firstProject?.name ?? projectKey}</span> ({projectKey}).</>
          ) : (
            <>No projects visible. Configure your Jira credentials in the server&apos;s .env, then refresh.</>
          )}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ListChecks className="h-4 w-4" /> Issues by status
            </CardTitle>
            <CardDescription>{totalIssues} issues across {statusData.buckets.length} statuses</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {statusData.buckets.length === 0 ? (
              <p className="text-sm text-muted-foreground">No issues yet.</p>
            ) : (
              statusData.buckets.map((bucket) => (
                <Badge key={bucket.status} variant="secondary" className="text-sm">
                  {bucket.status}: <span className="ml-1 font-semibold">{bucket.count}</span>
                </Badge>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Folder className="h-4 w-4" /> Top workload
            </CardTitle>
            <CardDescription>Open issues by assignee, top 5</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {topWorkload.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing assigned.</p>
            ) : (
              topWorkload.map((entry, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span>{entry.assignee?.display_name ?? "Unassigned"}</span>
                  <Badge variant="outline">{entry.open_issues}</Badge>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-4 w-4" /> Recent activity
            </CardTitle>
            <CardDescription>Issues updated in the last 2 days</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {recentRows.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recent updates.</p>
            ) : (
              recentRows.map((row) => (
                <Link
                  key={row.key}
                  href={`/issues/${row.key}`}
                  className="flex items-center justify-between gap-3 text-sm hover:underline"
                >
                  <span className="truncate">
                    <span className="font-mono text-xs text-muted-foreground">{row.key}</span> {row.summary}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatRelativeDate(row.updated)}</span>
                </Link>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href="/issues">Search issues</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/issues/new">Create issue</Link>
        </Button>
        <Button asChild variant="ghost">
          <Link href={config.jiraBrowseUrl} target="_blank" rel="noreferrer">
            Open Jira
          </Link>
        </Button>
      </div>
    </div>
  );
}
