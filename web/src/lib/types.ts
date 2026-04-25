export interface JiraIssue {
  key: string;
  id?: string;
  fields?: Record<string, unknown>;
  summary?: string | null;
  status?: string | null;
  assignee?: string | null;
  updated?: string | null;
  issuetype?: string | null;
  priority?: string | null;
}

export interface JiraProject {
  key: string;
  id?: string;
  name?: string;
  projectTypeKey?: string;
  lead?: string;
}

export interface JiraBoard {
  id: number;
  name: string;
  type?: string;
  projectKey?: string;
}

export interface JiraSprint {
  id: number;
  name: string;
  state?: "active" | "closed" | "future" | string;
  startDate?: string;
  endDate?: string;
  goal?: string;
}

export interface JiraTransition {
  id: string;
  name: string;
  to?: { id?: string; name?: string };
}

export interface JiraComment {
  id: string;
  author?: string | null;
  body?: string | null;
  created?: string | null;
  updated?: string | null;
}

export interface ToolDescriptor {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}
