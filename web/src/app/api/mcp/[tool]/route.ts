import { NextResponse } from "next/server";
import { callTool } from "@/lib/mcp-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ tool: string }> },
): Promise<Response> {
  const { tool } = await context.params;
  if (!tool) {
    return NextResponse.json({ error: "tool name required" }, { status: 400 });
  }
  let args: Record<string, unknown> = {};
  try {
    const text = await request.text();
    if (text) {
      const parsed = JSON.parse(text) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        args = parsed as Record<string, unknown>;
      }
    }
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  try {
    const result = await callTool(tool, args);
    return NextResponse.json({ result });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message, tool }, { status: 502 });
  }
}
