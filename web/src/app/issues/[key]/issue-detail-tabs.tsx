"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useMcpMutation } from "@/hooks/use-jira";
import { formatRelativeDate } from "@/lib/utils";

interface CommentRow {
  id: string;
  author: string;
  body: string;
  created: string | null;
}

interface TransitionRow {
  id: string;
  name: string;
  to?: { name?: string } | null;
}

interface Props {
  issueKey: string;
  description: string;
  labels: string[];
  comments: CommentRow[];
  transitions: TransitionRow[];
  updated: string | null;
}

const commentSchema = z.object({ body: z.string().min(1, "Comment body is required.") });
type CommentValues = z.infer<typeof commentSchema>;

export function IssueDetailTabs({ issueKey, description, labels, comments, transitions, updated }: Props): React.ReactElement {
  const router = useRouter();
  const addComment = useMcpMutation<Record<string, unknown>, { id: string }>("add_comment");
  const transitionIssue = useMcpMutation<Record<string, unknown>, { key: string }>("transition_issue");

  const form = useForm<CommentValues>({
    resolver: zodResolver(commentSchema),
    defaultValues: { body: "" },
  });

  const onAddComment = async (values: CommentValues): Promise<void> => {
    try {
      await addComment.mutateAsync({ key: issueKey, body: values.body });
      toast.success("Comment added");
      form.reset({ body: "" });
      router.refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to add comment");
    }
  };

  const onTransition = async (transitionId: string, name: string): Promise<void> => {
    try {
      await transitionIssue.mutateAsync({ key: issueKey, transition_id: transitionId });
      toast.success(`Transitioned to ${name}`);
      router.refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Transition failed");
    }
  };

  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="comments">Comments ({comments.length})</TabsTrigger>
        <TabsTrigger value="transitions">Transitions ({transitions.length})</TabsTrigger>
        <TabsTrigger value="activity">Activity</TabsTrigger>
      </TabsList>

      <TabsContent value="overview">
        <Card>
          <CardHeader>
            <CardTitle>Description</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <pre className="whitespace-pre-wrap rounded-md bg-muted p-4 text-sm">{description}</pre>
            {labels.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">Labels:</span>
                {labels.map((label) => (
                  <Badge key={label} variant="outline">
                    {label}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="comments">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Add comment</CardTitle>
              <CardDescription>Plain text. The server formats it before posting to Jira.</CardDescription>
            </CardHeader>
            <CardContent>
              <Form {...form}>
                <form onSubmit={form.handleSubmit(onAddComment)} className="flex flex-col gap-3">
                  <FormField
                    control={form.control}
                    name="body"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="sr-only">Comment</FormLabel>
                        <FormControl>
                          <Textarea rows={4} placeholder="Write a comment..." {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <div className="flex justify-end">
                    <Button type="submit" disabled={addComment.isPending}>
                      {addComment.isPending ? "Posting..." : "Post comment"}
                    </Button>
                  </div>
                </form>
              </Form>
            </CardContent>
          </Card>
          {comments.length === 0 ? (
            <p className="text-sm text-muted-foreground">No comments yet.</p>
          ) : (
            comments.map((c) => (
              <Card key={c.id}>
                <CardHeader>
                  <CardTitle className="text-sm">{c.author}</CardTitle>
                  <CardDescription>{formatRelativeDate(c.created)}</CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="whitespace-pre-wrap text-sm">{c.body}</p>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </TabsContent>

      <TabsContent value="transitions">
        <Card>
          <CardHeader>
            <CardTitle>Workflow transitions</CardTitle>
            <CardDescription>Move this issue to its next state. Restricted to transitions you can run right now.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {transitions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No available transitions.</p>
            ) : (
              transitions.map((t) => (
                <Button
                  key={t.id}
                  variant="outline"
                  disabled={transitionIssue.isPending}
                  onClick={() => onTransition(t.id, t.name)}
                >
                  {t.name}
                  {t.to?.name && <span className="ml-2 text-xs text-muted-foreground">to {t.to.name}</span>}
                </Button>
              ))
            )}
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="activity">
        <Card>
          <CardHeader>
            <CardTitle>Activity</CardTitle>
            <CardDescription>
              {updated ? `Last updated ${formatRelativeDate(updated)}.` : "No activity recorded."}
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Detailed change history is not exposed by the MCP server yet. Use the comments tab for collaboration history.
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
}
