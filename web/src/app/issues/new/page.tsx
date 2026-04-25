import { NewIssueForm } from "./new-issue-form";

export const dynamic = "force-dynamic";

export default function NewIssuePage(): React.ReactElement {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">New issue</h1>
        <p className="text-sm text-muted-foreground">Create a Jira issue through the create_issue MCP tool.</p>
      </div>
      <NewIssueForm />
    </div>
  );
}
