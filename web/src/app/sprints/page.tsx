import { SprintsClient } from "./sprints-client";

export const dynamic = "force-dynamic";

export default function SprintsPage(): React.ReactElement {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Sprints</h1>
        <p className="text-sm text-muted-foreground">Pick a board and a sprint to see its report.</p>
      </div>
      <SprintsClient />
    </div>
  );
}
