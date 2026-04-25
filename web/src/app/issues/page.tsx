import { IssuesSearchClient } from "./issues-search-client";

export const dynamic = "force-dynamic";

export default function IssuesPage(): React.ReactElement {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Issues</h1>
        <p className="text-sm text-muted-foreground">Run a JQL search against your Jira tenant.</p>
      </div>
      <IssuesSearchClient />
    </div>
  );
}
