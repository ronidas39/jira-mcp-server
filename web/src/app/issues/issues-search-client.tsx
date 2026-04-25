"use client";

import * as React from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useMcpQuery } from "@/hooks/use-jira";
import { toIssueRow, statusColor } from "@/lib/jira";
import { formatRelativeDate } from "@/lib/utils";

interface SearchResult {
  issues: unknown[];
  total: number;
}

const FIELD_OPTIONS = ["summary", "status", "assignee", "priority", "updated", "labels", "issuetype"];

export function IssuesSearchClient(): React.ReactElement {
  const [jqlInput, setJqlInput] = React.useState("ORDER BY updated DESC");
  const [maxResults, setMaxResults] = React.useState("25");
  const [fields, setFields] = React.useState<string[]>(["summary", "status", "assignee", "updated"]);
  const [submitted, setSubmitted] = React.useState({ jql: "ORDER BY updated DESC", max: 25, fields });

  const query = useMcpQuery<SearchResult>("search_issues", {
    jql: submitted.jql,
    max_results: submitted.max,
    fields: submitted.fields,
  });

  const onSubmit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setSubmitted({ jql: jqlInput.trim() || "ORDER BY updated DESC", max: Number(maxResults) || 25, fields });
  };

  const toggleField = (field: string): void => {
    setFields((prev) => (prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]));
  };

  const rows = (query.data?.issues ?? []).map(toIssueRow);

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-6">
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="jql">JQL</Label>
            <Input
              id="jql"
              value={jqlInput}
              onChange={(e) => setJqlInput(e.target.value)}
              placeholder="project = PROJ AND status != Done ORDER BY updated DESC"
              className="font-mono"
            />
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor="max-results">Max results</Label>
              <Select value={maxResults} onValueChange={setMaxResults}>
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[10, 25, 50, 100].map((n) => (
                    <SelectItem key={n} value={String(n)}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-1 flex-col gap-2">
              <Label>Fields</Label>
              <div className="flex flex-wrap gap-2">
                {FIELD_OPTIONS.map((field) => {
                  const active = fields.includes(field);
                  return (
                    <Button
                      key={field}
                      type="button"
                      variant={active ? "default" : "outline"}
                      size="sm"
                      onClick={() => toggleField(field)}
                    >
                      {field}
                    </Button>
                  );
                })}
              </div>
            </div>
            <Button type="submit">Run search</Button>
          </div>
        </form>

        {query.isError && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {query.error.message}
          </div>
        )}

        {query.isLoading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-32">Key</TableHead>
                  <TableHead>Summary</TableHead>
                  <TableHead className="w-32">Status</TableHead>
                  <TableHead className="w-40">Assignee</TableHead>
                  <TableHead className="w-32">Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
                      No matching issues.
                    </TableCell>
                  </TableRow>
                ) : (
                  rows.map((row) => (
                    <TableRow key={row.key} className="cursor-pointer">
                      <TableCell className="font-mono text-xs">
                        <Link href={`/issues/${row.key}`} className="hover:underline">
                          {row.key}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Link href={`/issues/${row.key}`} className="hover:underline">
                          {row.summary}
                        </Link>
                      </TableCell>
                      <TableCell>
                        {row.status ? <Badge variant={statusColor(row.status)}>{row.status}</Badge> : <span className="text-muted-foreground">-</span>}
                      </TableCell>
                      <TableCell>{row.assignee ?? <span className="text-muted-foreground">Unassigned</span>}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{formatRelativeDate(row.updated)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        )}

        <div className="text-xs text-muted-foreground">
          Showing {rows.length} of {query.data?.total ?? 0} matching issues.
        </div>
      </CardContent>
    </Card>
  );
}
