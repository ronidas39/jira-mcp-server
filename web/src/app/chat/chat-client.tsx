"use client";

import * as React from "react";
import { Send, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";

interface Message {
  role: "user" | "assistant";
  content: string;
  toolEvents?: Array<{ name: string; ok?: boolean; error?: string }>;
}

interface StreamEvent {
  type: "text" | "tool_call" | "tool_result" | "done" | "error";
  text?: string;
  name?: string;
  input?: unknown;
  ok?: boolean;
  error?: string;
}

export function ChatClient(): React.ReactElement {
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [draft, setDraft] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, pending]);

  const send = async (): Promise<void> => {
    const text = draft.trim();
    if (!text || pending) return;
    const next: Message[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setDraft("");
    setPending(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: next.map(({ role, content }) => ({ role, content })) }),
      });
      if (!res.ok || !res.body) {
        const errText = await res.text();
        setMessages((m) => [...m, { role: "assistant", content: `Error: ${errText}` }]);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let collectedText = "";
      const collectedEvents: Array<{ name: string; ok?: boolean; error?: string }> = [];
      setMessages((m) => [...m, { role: "assistant", content: "", toolEvents: [] }]);

      const apply = (): void => {
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { role: "assistant", content: collectedText, toolEvents: [...collectedEvents] };
          return copy;
        });
      };

      // Parse server-sent-events.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let event: StreamEvent;
          try {
            event = JSON.parse(payload) as StreamEvent;
          } catch {
            continue;
          }
          if (event.type === "text" && event.text) {
            collectedText += (collectedText ? "\n" : "") + event.text;
          } else if (event.type === "tool_call" && event.name) {
            collectedEvents.push({ name: event.name });
          } else if (event.type === "tool_result" && event.name) {
            const last = [...collectedEvents].reverse().find((e) => e.name === event.name && e.ok === undefined);
            if (last) {
              last.ok = event.ok;
              if (event.error) last.error = event.error;
            } else {
              collectedEvents.push({ name: event.name, ok: event.ok, error: event.error });
            }
          } else if (event.type === "error" && event.error) {
            collectedText += `\n\n[error] ${event.error}`;
          }
          apply();
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Stream failed";
      setMessages((m) => [...m, { role: "assistant", content: `Error: ${message}` }]);
    } finally {
      setPending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <Card className="flex flex-1 flex-col">
      <CardContent className="flex flex-1 flex-col gap-4 p-4">
        <div ref={scrollRef} className="flex-1 overflow-y-auto rounded-md border bg-background/50 p-4">
          {messages.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Try: &quot;What is in the active sprint?&quot; or &quot;Show me stale issues in TT.&quot;
            </p>
          ) : (
            <div className="flex flex-col gap-4">
              {messages.map((m, i) => (
                <div key={i} className={m.role === "user" ? "self-end max-w-[75%]" : "self-start max-w-[85%]"}>
                  <div
                    className={`whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
                      m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
                    }`}
                  >
                    {m.content || (pending && i === messages.length - 1 ? "..." : "")}
                  </div>
                  {m.toolEvents && m.toolEvents.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {m.toolEvents.map((t, j) => (
                        <Badge
                          key={j}
                          variant={t.ok === false ? "destructive" : "outline"}
                          className="text-[10px]"
                        >
                          <Wrench className="mr-1 h-3 w-3" />
                          {t.name}
                          {t.ok === false && t.error ? `: ${t.error}` : ""}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about issues, sprints, projects... (Enter to send, Shift+Enter for newline)"
            rows={2}
            className="flex-1 resize-none"
            disabled={pending}
          />
          <Button onClick={() => void send()} disabled={pending || !draft.trim()}>
            <Send className="mr-2 h-4 w-4" /> {pending ? "Thinking..." : "Send"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
