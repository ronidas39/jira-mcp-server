// Chat backend uses the manual MCP loop: list tools from the local MCP client,
// pass them as native Anthropic tool definitions, then service tool_use blocks
// by dispatching back through the MCP client. This works on every Anthropic
// plan, while the experimental mcp_servers parameter is still gated.
import { NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import type { MessageParam, Tool, ToolUseBlock, TextBlock } from "@anthropic-ai/sdk/resources/messages";
import { getServerEnv } from "@/lib/env";
import { callTool, listTools } from "@/lib/mcp-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SYSTEM_PROMPT = `You are the operator console for an internal Jira instance, exposed through MCP tools.
Use the supplied tools whenever a user asks about Jira issues, projects, sprints, or workload.
Read-only tools are safe to call without confirmation. Before any tool that mutates Jira state
(create_issue, update_issue, transition_issue, add_comment, link_issues, bulk_create_issues,
move_to_sprint, delete_issue), restate what you are about to do and ask the user to confirm.
Quote issue keys like PROJ-123 verbatim. Keep replies short and skim-friendly.`;

interface ChatRequestBody {
  messages: Array<{ role: "user" | "assistant"; content: string }>;
}

function isToolUse(block: ContentBlock): block is ToolUseBlock {
  return block.type === "tool_use";
}

type ContentBlock = TextBlock | ToolUseBlock | { type: string; [key: string]: unknown };

export async function POST(request: Request): Promise<Response> {
  const env = getServerEnv();
  if (!env.ANTHROPIC_API_KEY) {
    return NextResponse.json(
      { error: "ANTHROPIC_API_KEY is not configured. Set it in web/.env.local to enable chat." },
      { status: 503 },
    );
  }

  let body: ChatRequestBody;
  try {
    body = (await request.json()) as ChatRequestBody;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!body?.messages?.length) {
    return NextResponse.json({ error: "messages required" }, { status: 400 });
  }

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
  const mcpTools = await listTools();
  const tools: Tool[] = mcpTools.map((tool) => ({
    name: tool.name,
    description: tool.description ?? "",
    // The MCP SDK already returns a JSON Schema for inputs; Anthropic accepts the same shape.
    input_schema: (tool.inputSchema ?? { type: "object", properties: {} }) as Tool["input_schema"],
  }));

  const messages: MessageParam[] = body.messages.map((m) => ({ role: m.role, content: m.content }));

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (event: Record<string, unknown>): void => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      };
      try {
        // Loop bound: at most 8 tool rounds.
        for (let round = 0; round < 8; round += 1) {
          const response = await client.messages.create({
            model: "claude-sonnet-4-5",
            max_tokens: 1024,
            system: SYSTEM_PROMPT,
            tools,
            messages,
          });
          const textParts: string[] = [];
          for (const block of response.content as ContentBlock[]) {
            if (block.type === "text" && typeof (block as TextBlock).text === "string") {
              textParts.push((block as TextBlock).text);
            }
          }
          if (textParts.length) {
            send({ type: "text", text: textParts.join("\n") });
          }
          messages.push({ role: "assistant", content: response.content });
          if (response.stop_reason !== "tool_use") {
            break;
          }
          const toolResults: Array<{ type: "tool_result"; tool_use_id: string; content: string; is_error?: boolean }> = [];
          for (const block of response.content as ContentBlock[]) {
            if (!isToolUse(block)) continue;
            send({ type: "tool_call", name: block.name, input: block.input });
            try {
              const result = await callTool(block.name, (block.input as Record<string, unknown>) ?? {});
              const serialized = typeof result === "string" ? result : JSON.stringify(result);
              toolResults.push({ type: "tool_result", tool_use_id: block.id, content: serialized });
              send({ type: "tool_result", name: block.name, ok: true });
            } catch (error) {
              const message = error instanceof Error ? error.message : String(error);
              toolResults.push({ type: "tool_result", tool_use_id: block.id, content: message, is_error: true });
              send({ type: "tool_result", name: block.name, ok: false, error: message });
            }
          }
          messages.push({ role: "user", content: toolResults });
        }
        send({ type: "done" });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        send({ type: "error", error: message });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}

export async function GET(): Promise<Response> {
  const env = getServerEnv();
  return NextResponse.json({ enabled: Boolean(env.ANTHROPIC_API_KEY) });
}
