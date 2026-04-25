"use client";

import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { useMcpQuery } from "@/hooks/use-jira";
import { formatRelativeDate } from "@/lib/utils";

interface BoardsResult {
  boards: Array<{ id: number; name: string; type?: string }>;
}

interface SprintsResult {
  sprints: Array<{ id: number; name: string; state?: string; start_date?: string; end_date?: string; goal?: string | null }>;
}

interface SprintReportResult {
  committed?: number;
  delivered?: number;
  at_risk?: number;
  committed_points?: number;
  completed_points?: number;
  added_points?: number;
  removed_points?: number;
  issues?: Array<unknown>;
}

const STATE_OPTIONS = ["active", "future", "closed"];

export function SprintsClient(): React.ReactElement {
  const [boardId, setBoardId] = React.useState<string>("");
  const [state, setState] = React.useState<string>("active");
  const [sprintId, setSprintId] = React.useState<string>("");

  const boards = useMcpQuery<BoardsResult>("list_boards", {});
  const sprints = useMcpQuery<SprintsResult>(
    boardId ? "list_sprints" : null,
    { board_id: Number(boardId), state },
    Boolean(boardId),
  );
  const report = useMcpQuery<SprintReportResult>(
    sprintId ? "sprint_report" : null,
    { sprint_id: Number(sprintId) },
    Boolean(sprintId),
  );

  React.useEffect(() => {
    setSprintId("");
  }, [boardId, state]);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Pickers</CardTitle>
          <CardDescription>Choose a board, a sprint state, then a sprint.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          <div className="flex flex-col gap-2">
            <Label>Board</Label>
            <Select value={boardId} onValueChange={setBoardId}>
              <SelectTrigger className="w-72">
                <SelectValue placeholder={boards.isLoading ? "Loading boards..." : "Select board"} />
              </SelectTrigger>
              <SelectContent>
                {(boards.data?.boards ?? []).map((b) => (
                  <SelectItem key={b.id} value={String(b.id)}>
                    {b.name} {b.type ? `(${b.type})` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label>State</Label>
            <Select value={state} onValueChange={setState}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATE_OPTIONS.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label>Sprint</Label>
            <Select value={sprintId} onValueChange={setSprintId} disabled={!boardId}>
              <SelectTrigger className="w-72">
                <SelectValue placeholder={!boardId ? "Pick a board first" : sprints.isLoading ? "Loading sprints..." : "Select sprint"} />
              </SelectTrigger>
              <SelectContent>
                {(sprints.data?.sprints ?? []).map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name} {s.state ? `(${s.state})` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {sprintId && (
        <Card>
          <CardHeader>
            <CardTitle>Sprint report</CardTitle>
            <CardDescription>Committed, delivered, and at-risk metrics from sprint_report.</CardDescription>
          </CardHeader>
          <CardContent>
            {report.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : report.isError ? (
              <p className="text-sm text-destructive">{report.error.message}</p>
            ) : report.data ? (
              <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="Committed" value={report.data.committed_points ?? report.data.committed ?? 0} />
                <Stat label="Delivered" value={report.data.completed_points ?? report.data.delivered ?? 0} />
                <Stat label="At risk" value={report.data.at_risk ?? 0} />
              </div>
            ) : null}
          </CardContent>
        </Card>
      )}

      {sprints.data?.sprints && sprints.data.sprints.length > 0 && !sprintId && (
        <Card>
          <CardHeader>
            <CardTitle>Sprints in {state} state</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {sprints.data.sprints.map((s) => (
              <div key={s.id} className="flex items-center justify-between text-sm">
                <span>
                  <span className="font-medium">{s.name}</span>
                  {s.goal && <span className="ml-2 text-muted-foreground">{s.goal}</span>}
                </span>
                <Badge variant="outline">{formatRelativeDate(s.end_date)}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }): React.ReactElement {
  return (
    <div className="rounded-md border bg-card p-4">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className="text-3xl font-semibold">{value}</div>
    </div>
  );
}
