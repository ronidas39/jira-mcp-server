"use client";

import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query";

async function callMcp<T>(tool: string, args: Record<string, unknown>): Promise<T> {
  const res = await fetch(`/api/mcp/${tool}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  const json = (await res.json()) as { result?: T; error?: string };
  if (!res.ok || json.error) {
    throw new Error(json.error ?? `Tool ${tool} failed (${res.status})`);
  }
  return json.result as T;
}

export interface ToolMeta {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export function useTools(): UseQueryResult<ToolMeta[], Error> {
  return useQuery({
    queryKey: ["mcp", "tools"],
    queryFn: async () => {
      const res = await fetch("/api/mcp/tools");
      const json = (await res.json()) as { tools?: ToolMeta[]; error?: string };
      if (!res.ok || json.error) throw new Error(json.error ?? "failed to list tools");
      return json.tools ?? [];
    },
  });
}

export function useMcpQuery<T>(tool: string | null, args: Record<string, unknown>, enabled = true): UseQueryResult<T, Error> {
  return useQuery<T, Error>({
    queryKey: ["mcp", tool, args],
    queryFn: () => callMcp<T>(tool as string, args),
    enabled: enabled && Boolean(tool),
  });
}

export function useMcpMutation<TInput extends Record<string, unknown>, TResult>(tool: string, invalidate: string[][] = []): UseMutationResult<TResult, Error, TInput> {
  const qc = useQueryClient();
  return useMutation<TResult, Error, TInput>({
    mutationFn: (args) => callMcp<TResult>(tool, args),
    onSuccess: () => {
      for (const key of invalidate) qc.invalidateQueries({ queryKey: key });
    },
  });
}

export { callMcp };
