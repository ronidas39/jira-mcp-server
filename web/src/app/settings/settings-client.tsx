"use client";

import * as React from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTools } from "@/hooks/use-jira";
import { McpToolForm } from "@/components/mcp-tool-form";

interface PublicConfig {
  mcpServerUrl: string;
  jiraBrowseUrl: string;
  chatEnabled: boolean;
}

type Status =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ok"; detail: string }
  | { state: "error"; detail: string };

export function SettingsClient({ config }: { config: PublicConfig }): React.ReactElement {
  const [mcpStatus, setMcpStatus] = React.useState<Status>({ state: "idle" });
  const [chatStatus, setChatStatus] = React.useState<Status>({ state: "idle" });

  const pingMcp = async (): Promise<void> => {
    setMcpStatus({ state: "loading" });
    try {
      const res = await fetch("/api/mcp/tools", { cache: "no-store" });
      const json = (await res.json()) as { tools?: Array<{ name: string }>; error?: string };
      if (!res.ok || json.error) {
        setMcpStatus({ state: "error", detail: json.error ?? `${res.status}` });
      } else {
        setMcpStatus({ state: "ok", detail: `${json.tools?.length ?? 0} tools available` });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Network error";
      setMcpStatus({ state: "error", detail: message });
    }
  };

  const pingChat = async (): Promise<void> => {
    setChatStatus({ state: "loading" });
    try {
      const res = await fetch("/api/chat", { method: "GET", cache: "no-store" });
      const json = (await res.json()) as { enabled?: boolean; error?: string };
      if (!res.ok || json.error) {
        setChatStatus({ state: "error", detail: json.error ?? `${res.status}` });
      } else if (json.enabled) {
        setChatStatus({ state: "ok", detail: "ANTHROPIC_API_KEY is configured" });
      } else {
        setChatStatus({ state: "error", detail: "ANTHROPIC_API_KEY not set" });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Network error";
      setChatStatus({ state: "error", detail: message });
    }
  };

  React.useEffect(() => {
    void pingMcp();
  }, []);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>MCP server</CardTitle>
          <CardDescription>Pings the local route, which proxies to the configured Python server.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <Row label="MCP_SERVER_URL" value={config.mcpServerUrl} />
          <StatusRow status={mcpStatus} />
          <div>
            <Button variant="outline" size="sm" onClick={() => void pingMcp()} disabled={mcpStatus.state === "loading"}>
              {mcpStatus.state === "loading" ? "Probing..." : "Probe again"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Chat key</CardTitle>
          <CardDescription>Confirms whether the chat route can reach Anthropic.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <Row label="ANTHROPIC_API_KEY" value={config.chatEnabled ? "set" : "not set"} />
          <StatusRow status={chatStatus} />
          <div>
            <Button variant="outline" size="sm" onClick={() => void pingChat()} disabled={chatStatus.state === "loading"}>
              {chatStatus.state === "loading" ? "Testing..." : "Test chat key"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Jira links</CardTitle>
          <CardDescription>Used to build &quot;Open in Jira&quot; buttons.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <Row label="JIRA_BROWSE_URL" value={config.jiraBrowseUrl} />
        </CardContent>
      </Card>

      <div className="md:col-span-2">
        <ToolPlayground />
      </div>
    </div>
  );
}

function ToolPlayground(): React.ReactElement {
  const tools = useTools();
  const [selected, setSelected] = React.useState<string>("");
  const tool = tools.data?.find((t) => t.name === selected);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tool playground</CardTitle>
        <CardDescription>
          Reach any tool that does not have a dedicated page (update_issue, link_issues, bulk_create_issues...).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Select value={selected} onValueChange={setSelected}>
          <SelectTrigger className="w-72">
            <SelectValue placeholder={tools.isLoading ? "Loading tools..." : "Pick a tool"} />
          </SelectTrigger>
          <SelectContent>
            {(tools.data ?? []).map((t) => (
              <SelectItem key={t.name} value={t.name}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {tool && tool.inputSchema ? (
          <McpToolForm
            toolName={tool.name}
            description={tool.description}
            inputSchema={tool.inputSchema as Parameters<typeof McpToolForm>[0]["inputSchema"]}
          />
        ) : (
          <p className="text-sm text-muted-foreground">Pick a tool above to see its inputs.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-mono text-xs">{value}</span>
    </div>
  );
}

function StatusRow({ status }: { status: Status }): React.ReactElement {
  if (status.state === "idle") return <Badge variant="outline">unknown</Badge>;
  if (status.state === "loading") return <Badge variant="outline">probing...</Badge>;
  if (status.state === "ok")
    return (
      <Badge className="w-fit" variant="secondary">
        <CheckCircle2 className="mr-1 h-3 w-3" /> {status.detail}
      </Badge>
    );
  return (
    <Badge className="w-fit" variant="destructive">
      <XCircle className="mr-1 h-3 w-3" /> {status.detail}
    </Badge>
  );
}
