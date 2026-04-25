import { ChatClient } from "./chat-client";

export const dynamic = "force-dynamic";

export default async function ChatPage(): Promise<React.ReactElement> {
  let enabled = false;
  try {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_INTERNAL_BASE_URL ?? "http://localhost:3000"}/api/chat`,
      { cache: "no-store" },
    );
    enabled = res.ok && (((await res.json()) as { enabled?: boolean }).enabled === true);
  } catch {
    enabled = Boolean(process.env.ANTHROPIC_API_KEY);
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] flex-col gap-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Chat</h1>
        <p className="text-sm text-muted-foreground">Ask Claude about your Jira data; tools are wired through the MCP server.</p>
      </div>
      {enabled ? (
        <ChatClient />
      ) : (
        <div className="rounded-md border bg-muted/30 p-6 text-sm">
          <p className="font-medium">Chat is disabled.</p>
          <p className="text-muted-foreground">
            Set <code className="rounded bg-muted px-1">ANTHROPIC_API_KEY</code> in <code className="rounded bg-muted px-1">web/.env.local</code> to enable it.
          </p>
        </div>
      )}
    </div>
  );
}
