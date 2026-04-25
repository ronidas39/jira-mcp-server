"use client";

import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z, type ZodTypeAny } from "zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMcpMutation } from "@/hooks/use-jira";

interface JsonSchemaProperty {
  type?: string | string[];
  description?: string;
  enum?: unknown[];
  items?: JsonSchemaProperty;
  default?: unknown;
}

interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

type FieldKind = "string" | "number" | "boolean" | "array" | "object";

function fieldKind(prop: JsonSchemaProperty): FieldKind {
  const type = Array.isArray(prop.type) ? prop.type.find((t) => t !== "null") : prop.type;
  if (type === "integer" || type === "number") return "number";
  if (type === "boolean") return "boolean";
  if (type === "array") return "array";
  if (type === "object") return "object";
  return "string";
}

function buildSchema(schema: JsonSchema): ZodTypeAny {
  const shape: Record<string, ZodTypeAny> = {};
  const required = new Set(schema.required ?? []);
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    const kind = fieldKind(prop);
    let validator: ZodTypeAny;
    if (kind === "number") {
      validator = z.coerce.number();
    } else if (kind === "boolean") {
      validator = z.coerce.boolean();
    } else {
      validator = z.string();
    }
    if (!required.has(key)) {
      validator = validator.optional().or(z.literal("").transform(() => undefined));
    }
    shape[key] = validator;
  }
  return z.object(shape);
}

function coerceArray(value: string): unknown[] {
  if (!value.trim()) return [];
  // Support comma-separated values or JSON arrays.
  if (value.trim().startsWith("[")) {
    try {
      const parsed = JSON.parse(value) as unknown;
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // Falls through to comma split.
    }
  }
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

function coerceObject(value: string): Record<string, unknown> | undefined {
  if (!value.trim()) return undefined;
  try {
    const parsed = JSON.parse(value) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // Ignored.
  }
  return undefined;
}

export interface McpToolFormProps {
  toolName: string;
  description?: string;
  inputSchema: JsonSchema;
  onSuccess?: (result: unknown) => void;
}

export function McpToolForm({ toolName, description, inputSchema, onSuccess }: McpToolFormProps): React.ReactElement {
  const zodSchema = React.useMemo(() => buildSchema(inputSchema), [inputSchema]);
  const mutation = useMcpMutation<Record<string, unknown>, unknown>(toolName);
  const [result, setResult] = React.useState<unknown>(null);

  const form = useForm({
    resolver: zodResolver(zodSchema),
    defaultValues: Object.fromEntries(
      Object.entries(inputSchema.properties ?? {}).map(([k, prop]) => [k, prop.default ?? ""]),
    ),
  });

  const onSubmit = async (values: Record<string, unknown>): Promise<void> => {
    const args: Record<string, unknown> = {};
    for (const [key, prop] of Object.entries(inputSchema.properties ?? {})) {
      const raw = values[key];
      if (raw === undefined || raw === null || raw === "") continue;
      const kind = fieldKind(prop);
      if (kind === "array") {
        args[key] = coerceArray(String(raw));
      } else if (kind === "object") {
        const obj = coerceObject(String(raw));
        if (obj !== undefined) args[key] = obj;
      } else if (kind === "boolean") {
        args[key] = raw === true || raw === "true";
      } else if (kind === "number") {
        args[key] = Number(raw);
      } else {
        args[key] = raw;
      }
    }
    try {
      const data = await mutation.mutateAsync(args);
      setResult(data);
      onSuccess?.(data);
      toast.success(`${toolName} succeeded`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Tool call failed");
    }
  };

  const properties = Object.entries(inputSchema.properties ?? {});

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-mono text-base">{toolName}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-3">
            {properties.length === 0 && <p className="text-sm text-muted-foreground">No inputs.</p>}
            {properties.map(([name, prop]) => {
              const kind = fieldKind(prop);
              return (
                <FormField
                  key={name}
                  control={form.control}
                  name={name}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        {name} <span className="text-xs text-muted-foreground">({kind})</span>
                      </FormLabel>
                      <FormControl>
                        {kind === "boolean" ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={field.value === true || field.value === "true"}
                              onChange={(e) => field.onChange(e.target.checked)}
                              className="h-4 w-4"
                            />
                            <Label htmlFor={field.name}>{prop.description ?? name}</Label>
                          </div>
                        ) : kind === "object" || kind === "array" ? (
                          <Textarea
                            placeholder={kind === "array" ? "comma,separated or JSON array" : "JSON object"}
                            value={(field.value as string) ?? ""}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            ref={field.ref}
                            name={field.name}
                            rows={3}
                          />
                        ) : (
                          <Input
                            type={kind === "number" ? "number" : "text"}
                            placeholder={prop.description}
                            value={(field.value as string) ?? ""}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            ref={field.ref}
                            name={field.name}
                          />
                        )}
                      </FormControl>
                      {prop.description && <p className="text-xs text-muted-foreground">{prop.description}</p>}
                      <FormMessage />
                    </FormItem>
                  )}
                />
              );
            })}
            <div>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Calling..." : "Call tool"}
              </Button>
            </div>
          </form>
        </Form>
        {result !== null && (
          <pre className="mt-4 max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}
