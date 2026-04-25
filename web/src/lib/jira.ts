// Helpers that pluck human-readable values from the Pydantic-snake-case JSON
// the Python MCP tools return. Tools serialize via model_dump(mode="json") so
// fields are snake_case. We accept any-shape input and read defensively.

export interface IssueRowSummary {
  key: string;
  summary: string;
  status: string | null;
  assignee: string | null;
  priority: string | null;
  updated: string | null;
}

interface SummaryLike {
  key?: string;
  summary?: string;
  status?: { name?: string } | string | null;
  assignee?: { display_name?: string; email_address?: string } | string | null;
  priority?: { name?: string } | string | null;
  updated?: string | null;
}

function readName(value: unknown): string | null {
  if (!value) return null;
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) {
    const v = value as { name?: string; display_name?: string; email_address?: string };
    return v.display_name ?? v.name ?? v.email_address ?? null;
  }
  return null;
}

export function toIssueRow(input: unknown): IssueRowSummary {
  const obj = (input ?? {}) as SummaryLike;
  return {
    key: obj.key ?? "",
    summary: obj.summary ?? "",
    status: readName(obj.status),
    assignee: readName(obj.assignee),
    priority: readName(obj.priority),
    updated: typeof obj.updated === "string" ? obj.updated : null,
  };
}

export function jiraIssueUrl(browseBase: string, key: string): string {
  return `${browseBase.replace(/\/$/, "")}/browse/${encodeURIComponent(key)}`;
}

export function statusColor(status: string | null | undefined): "default" | "secondary" | "destructive" | "outline" {
  if (!status) return "outline";
  const s = status.toLowerCase();
  if (s.includes("done") || s.includes("closed") || s.includes("resolved")) return "secondary";
  if (s.includes("progress")) return "default";
  if (s.includes("blocked") || s.includes("at risk")) return "destructive";
  return "outline";
}
