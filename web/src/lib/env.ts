import { z } from "zod";

const serverSchema = z.object({
  MCP_SERVER_URL: z.string().url().default("http://localhost:8765/mcp"),
  ANTHROPIC_API_KEY: z.string().optional(),
  JIRA_BROWSE_URL: z.string().url().default("https://ttmcp.atlassian.net"),
});

export type ServerEnv = z.infer<typeof serverSchema>;

let cached: ServerEnv | null = null;

export function getServerEnv(): ServerEnv {
  if (cached) return cached;
  const parsed = serverSchema.safeParse({
    MCP_SERVER_URL: process.env.MCP_SERVER_URL,
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
    JIRA_BROWSE_URL: process.env.JIRA_BROWSE_URL,
  });
  if (!parsed.success) {
    throw new Error(`Invalid environment configuration: ${parsed.error.message}`);
  }
  cached = parsed.data;
  return cached;
}

export function publicConfig(): { mcpServerUrl: string; jiraBrowseUrl: string; chatEnabled: boolean } {
  const env = getServerEnv();
  return {
    mcpServerUrl: env.MCP_SERVER_URL,
    jiraBrowseUrl: env.JIRA_BROWSE_URL,
    chatEnabled: Boolean(env.ANTHROPIC_API_KEY && env.ANTHROPIC_API_KEY.length > 0),
  };
}
