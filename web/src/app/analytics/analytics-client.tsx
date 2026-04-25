"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useMcpQuery } from "@/hooks/use-jira";
import { formatRelativeDate } from "@/lib/utils";
import { toIssueRow } from "@/lib/jira";

interface ProjectsResult {
  projects: Array<{ key: string; name: string }>;
}

interface WorkloadResult {
  entries: Array<{ assignee: { display_name?: string } | null; open_issues: number }>;
}

interface StatusResult {
  buckets: Array<{ status: string; count: number }>;
}

interface StaleResult {
  issues: Array<unknown>;
}

const CHART_HUES = [220, 160, 30, 280, 340, 200, 100, 50, 320, 240];

export function AnalyticsClient(): React.ReactElement {
  const searchParams = useSearchParams();
  const initialProject = searchParams.get("project") ?? "";
  const [projectKey, setProjectKey] = React.useState(initialProject);
  const projects = useMcpQuery<ProjectsResult>("list_projects", {});

  React.useEffect(() => {
    if (!projectKey && projects.data?.projects?.[0]?.key) {
      setProjectKey(projects.data.projects[0].key);
    }
  }, [projectKey, projects.data]);

  const workload = useMcpQuery<WorkloadResult>(projectKey ? "workload_by_assignee" : null, { project_key: projectKey }, Boolean(projectKey));
  const status = useMcpQuery<StatusResult>(projectKey ? "issues_by_status" : null, { project_key: projectKey }, Boolean(projectKey));
  const stale = useMcpQuery<StaleResult>(projectKey ? "stale_issues" : null, { project_key: projectKey, days: 14 }, Boolean(projectKey));

  const workloadEntries = workload.data?.entries ?? [];
  const workloadMax = workloadEntries.reduce((m, e) => Math.max(m, e.open_issues), 0);
  const buckets = status.data?.buckets ?? [];
  const statusTotal = buckets.reduce((sum, b) => sum + b.count, 0);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Project</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <div className="flex flex-col gap-2">
            <Label>Active project</Label>
            <Select value={projectKey} onValueChange={setProjectKey}>
              <SelectTrigger className="w-72">
                <SelectValue placeholder={projects.isLoading ? "Loading projects..." : "Pick a project"} />
              </SelectTrigger>
              <SelectContent>
                {(projects.data?.projects ?? []).map((p) => (
                  <SelectItem key={p.key} value={p.key}>
                    {p.key} - {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Workload by assignee</CardTitle>
            <CardDescription>Open issues per person.</CardDescription>
          </CardHeader>
          <CardContent>
            {workload.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : workloadEntries.length === 0 ? (
              <p className="text-sm text-muted-foreground">No data.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {workloadEntries.map((entry, i) => {
                  const width = workloadMax > 0 ? Math.round((entry.open_issues / workloadMax) * 100) : 0;
                  return (
                    <div key={i} className="flex items-center gap-3 text-sm">
                      <div className="w-40 truncate">{entry.assignee?.display_name ?? "Unassigned"}</div>
                      <div className="relative h-4 flex-1 rounded-full bg-muted">
                        <div
                          className="absolute left-0 top-0 h-4 rounded-full bg-primary"
                          style={{ width: `${width}%` }}
                        />
                      </div>
                      <div className="w-10 text-right text-xs text-muted-foreground">{entry.open_issues}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Issues by status</CardTitle>
            <CardDescription>Distribution across the workflow.</CardDescription>
          </CardHeader>
          <CardContent>
            {status.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : buckets.length === 0 ? (
              <p className="text-sm text-muted-foreground">No data.</p>
            ) : (
              <div className="flex flex-col gap-3">
                <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
                  {buckets.map((b, i) => {
                    const pct = statusTotal > 0 ? (b.count / statusTotal) * 100 : 0;
                    if (pct === 0) return null;
                    return (
                      <div
                        key={b.status}
                        title={`${b.status}: ${b.count}`}
                        style={{ width: `${pct}%`, backgroundColor: `hsl(${CHART_HUES[i % CHART_HUES.length]} 70% 55%)` }}
                      />
                    );
                  })}
                </div>
                <div className="grid gap-2 text-sm sm:grid-cols-2">
                  {buckets.map((b, i) => (
                    <div key={b.status} className="flex items-center gap-2">
                      <span
                        className="h-3 w-3 rounded-full"
                        style={{ backgroundColor: `hsl(${CHART_HUES[i % CHART_HUES.length]} 70% 55%)` }}
                      />
                      <span className="flex-1 truncate">{b.status}</span>
                      <span className="text-muted-foreground">{b.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Stale issues</CardTitle>
          <CardDescription>Open issues with no update in 14 or more days.</CardDescription>
        </CardHeader>
        <CardContent>
          {stale.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-32">Key</TableHead>
                  <TableHead>Summary</TableHead>
                  <TableHead className="w-32">Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(stale.data?.issues ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground">
                      Nothing stale. Nice work.
                    </TableCell>
                  </TableRow>
                ) : (
                  (stale.data?.issues ?? []).map((raw) => {
                    const r = toIssueRow(raw);
                    return (
                      <TableRow key={r.key}>
                        <TableCell className="font-mono text-xs">
                          <Link href={`/issues/${r.key}`} className="hover:underline">
                            {r.key}
                          </Link>
                        </TableCell>
                        <TableCell>{r.summary}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{formatRelativeDate(r.updated)}</TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
