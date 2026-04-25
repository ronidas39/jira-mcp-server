import { AnalyticsClient } from "./analytics-client";

export const dynamic = "force-dynamic";

export default function AnalyticsPage(): React.ReactElement {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <p className="text-sm text-muted-foreground">Workload, status mix, and stale issues.</p>
      </div>
      <AnalyticsClient />
    </div>
  );
}
