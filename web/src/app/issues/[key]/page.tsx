import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { callTool } from "@/lib/mcp-client";
import { publicConfig } from "@/lib/env";
import { jiraIssueUrl, statusColor } from "@/lib/jira";
import { formatRelativeDate } from "@/lib/utils";
import { IssueDetailTabs } from "./issue-detail-tabs";

export const dynamic = "force-dynamic";

interface IssueResult {
  issue?: {
    key: string;
    summary?: string;
    status?: { name?: string } | null;
    assignee?: { display_name?: string } | null;
    priority?: { name?: string } | null;
    issue_type?: { name?: string } | null;
    description?: unknown;
    labels?: string[];
    updated?: string;
    comments?: Array<{
      id: string;
      author?: { display_name?: string } | null;
      body?: unknown;
      created?: string;
    }>;
  };
}

interface TransitionsResult {
  transitions: Array<{ id: string; name: string; to?: { name?: string } | null }>;
}

function adfToText(value: unknown): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value !== "object") return "";
  const node = value as { type?: string; text?: string; content?: unknown[] };
  if (node.text) return node.text;
  if (Array.isArray(node.content)) {
    const sep = node.type === "paragraph" || node.type === "doc" ? "\n" : " ";
    return node.content.map(adfToText).join(sep);
  }
  return "";
}

export default async function IssueDetailPage({
  params,
}: {
  params: Promise<{ key: string }>;
}): Promise<React.ReactElement> {
  const { key: rawKey } = await params;
  const key = decodeURIComponent(rawKey);
  let issueData: IssueResult = {};
  let errorMessage: string | null = null;
  try {
    issueData = (await callTool("get_issue", {
      key,
      expand_comments: true,
      expand_transitions: true,
    })) as IssueResult;
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : "Failed to load issue";
  }

  const transitionsData = errorMessage
    ? { transitions: [] }
    : ((await callTool("list_transitions", { key }).catch(() => ({ transitions: [] }))) as TransitionsResult);

  const issue = issueData.issue;
  const config = publicConfig();
  const description = adfToText(issue?.description) || "No description.";
  const comments = (issue?.comments ?? []).map((c) => ({
    id: c.id,
    author: c.author?.display_name ?? "Unknown",
    body: adfToText(c.body),
    created: c.created ?? null,
  }));

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="font-mono">{key}</span>
            {issue?.issue_type?.name && <Badge variant="outline">{issue.issue_type.name}</Badge>}
          </div>
          <h1 className="text-2xl font-semibold">{issue?.summary ?? key}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            {issue?.status?.name && <Badge variant={statusColor(issue.status.name)}>{issue.status.name}</Badge>}
            {issue?.priority?.name && <Badge variant="outline">{issue.priority.name}</Badge>}
            {issue?.assignee?.display_name ? (
              <span className="text-muted-foreground">Assigned to {issue.assignee.display_name}</span>
            ) : (
              <span className="text-muted-foreground">Unassigned</span>
            )}
            {issue?.updated && (
              <span className="text-muted-foreground">Updated {formatRelativeDate(issue.updated)}</span>
            )}
          </div>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={jiraIssueUrl(config.jiraBrowseUrl, key)} target="_blank" rel="noreferrer">
            Open in Jira <ExternalLink className="ml-2 h-3 w-3" />
          </Link>
        </Button>
      </div>

      {errorMessage ? (
        <Card>
          <CardHeader>
            <CardTitle>Could not load issue</CardTitle>
            <CardDescription>{errorMessage}</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Confirm the key, then try again.
          </CardContent>
        </Card>
      ) : (
        <IssueDetailTabs
          issueKey={key}
          description={description}
          labels={issue?.labels ?? []}
          comments={comments}
          transitions={transitionsData.transitions}
          updated={issue?.updated ?? null}
        />
      )}
    </div>
  );
}
