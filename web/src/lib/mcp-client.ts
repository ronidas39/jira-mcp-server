import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { getServerEnv } from "@/lib/env";

interface CachedClient {
  client: Client;
  url: string;
}

declare global {
  // eslint-disable-next-line no-var
  var __mcpClient: CachedClient | undefined;
}

async function buildClient(url: string): Promise<Client> {
  const transport = new StreamableHTTPClientTransport(new URL(url));
  const client = new Client(
    { name: "jira-mcp-web", version: "0.1.0" },
    { capabilities: {} },
  );
  await client.connect(transport);
  return client;
}

export async function getMcpClient(): Promise<Client> {
  const env = getServerEnv();
  const url = env.MCP_SERVER_URL;
  if (globalThis.__mcpClient && globalThis.__mcpClient.url === url) {
    return globalThis.__mcpClient.client;
  }
  if (globalThis.__mcpClient && globalThis.__mcpClient.url !== url) {
    try {
      await globalThis.__mcpClient.client.close();
    } catch {
      // Best-effort close on URL switch.
    }
    globalThis.__mcpClient = undefined;
  }
  const client = await buildClient(url);
  globalThis.__mcpClient = { client, url };
  return client;
}

export interface CallToolResult {
  content: Array<{ type: string; text?: string; data?: unknown }>;
  structuredContent?: unknown;
  isError?: boolean;
}

export async function callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
  const client = await getMcpClient();
  const result = (await client.callTool({ name, arguments: args })) as CallToolResult;
  if (result.isError) {
    const message = result.content
      ?.map((part) => (part.type === "text" ? part.text : ""))
      .filter(Boolean)
      .join("\n");
    throw new Error(message || `Tool ${name} returned an error`);
  }
  if (result.structuredContent !== undefined) {
    return result.structuredContent;
  }
  const text = result.content
    ?.map((part) => (part.type === "text" ? part.text : ""))
    .filter(Boolean)
    .join("\n");
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function listTools(): Promise<Array<{ name: string; description?: string; inputSchema?: Record<string, unknown> }>> {
  const client = await getMcpClient();
  const res = await client.listTools();
  return res.tools.map((tool) => ({
    name: tool.name,
    description: tool.description ?? undefined,
    inputSchema: (tool.inputSchema ?? undefined) as Record<string, unknown> | undefined,
  }));
}
