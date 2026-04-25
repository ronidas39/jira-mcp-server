import { publicConfig } from "@/lib/env";
import { SettingsClient } from "./settings-client";

export const dynamic = "force-dynamic";

export default function SettingsPage(): React.ReactElement {
  const config = publicConfig();
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">Inspect your environment and probe the MCP server.</p>
      </div>
      <SettingsClient config={config} />
    </div>
  );
}
