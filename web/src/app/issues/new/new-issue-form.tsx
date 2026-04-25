"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMcpQuery, useMcpMutation } from "@/hooks/use-jira";

const schema = z.object({
  project_key: z.string().min(1, "Pick a project."),
  issue_type: z.string().min(1, "Pick an issue type."),
  summary: z.string().min(1, "Summary is required.").max(255),
  description: z.string().optional(),
  priority: z.string().optional(),
  labels: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

interface ProjectsResult {
  projects: Array<{ key: string; name: string; project_type_key?: string }>;
}

interface CreateIssueResult {
  key: string;
  id?: string;
}

const DEFAULT_TYPES = ["Task", "Story", "Bug", "Epic"];

export function NewIssueForm(): React.ReactElement {
  const router = useRouter();
  const projectsQuery = useMcpQuery<ProjectsResult>("list_projects", {});
  const createMutation = useMcpMutation<Record<string, unknown>, CreateIssueResult>("create_issue", [["mcp", "search_issues"]]);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { project_key: "", issue_type: "Task", summary: "", description: "", priority: "", labels: "" },
  });

  const onSubmit = async (values: FormValues): Promise<void> => {
    const labels = values.labels?.split(",").map((s) => s.trim()).filter(Boolean) ?? [];
    const payload: Record<string, unknown> = {
      project_key: values.project_key,
      issue_type: values.issue_type,
      summary: values.summary,
    };
    if (values.description) payload.description = values.description;
    if (values.priority) payload.priority = values.priority;
    if (labels.length) payload.labels = labels;
    try {
      const result = await createMutation.mutateAsync(payload);
      toast.success(`Issue ${result.key} created`);
      router.push(`/issues/${result.key}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to create issue");
    }
  };

  const projects = projectsQuery.data?.projects ?? [];

  return (
    <Card>
      <CardContent className="p-6">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                control={form.control}
                name="project_key"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Project</FormLabel>
                    <FormControl>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <SelectTrigger>
                          <SelectValue placeholder={projectsQuery.isLoading ? "Loading projects..." : "Select project"} />
                        </SelectTrigger>
                        <SelectContent>
                          {projects.map((p) => (
                            <SelectItem key={p.key} value={p.key}>
                              {p.key} - {p.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="issue_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Issue type</FormLabel>
                    <FormControl>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {DEFAULT_TYPES.map((t) => (
                            <SelectItem key={t} value={t}>
                              {t}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <FormField
              control={form.control}
              name="summary"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Summary</FormLabel>
                  <FormControl>
                    <Input placeholder="One-line title" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea rows={6} placeholder="Plain text. Markdown is converted server-side." {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                control={form.control}
                name="priority"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Priority (optional)</FormLabel>
                    <FormControl>
                      <Input placeholder="High" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="labels"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Labels (comma-separated)</FormLabel>
                    <FormControl>
                      <Input placeholder="ux, backend" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? "Creating..." : "Create issue"}
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
