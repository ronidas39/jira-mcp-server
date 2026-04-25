import { NextResponse } from "next/server";
import { listTools } from "@/lib/mcp-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    const tools = await listTools();
    return NextResponse.json({ tools });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
