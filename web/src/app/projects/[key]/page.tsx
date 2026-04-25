import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { callTool } from "@/lib/mcp-client";

export const dynamic = "force-dynamic";

interface ProjectResult {
  project?: {
    id?: string;
    key: string;
    name: string;
    project_type_key?: string;
    description?: string | null;
    lead?: { display_name?: string; email_address?: string } | null;
  };
}

interface CustomFieldsResult {
  fields?: Array<{ id: string; name: string; type?: string; schema?: { type?: string } | null }>;
  custom_fields?: Array<{ id: string; name: string; type?: string }>;
}

export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ key: string }>;
}): Promise<React.ReactElement> {
  const { key: rawKey } = await params;
  const key = decodeURIComponent(rawKey);
  let project: ProjectResult["project"] = undefined;
  let projectError: string | null = null;
  try {
    const result = (await callTool("get_project", { key_or_id: key })) as ProjectResult;
    project = result.project;
  } catch (error) {
    projectError = error instanceof Error ? error.message : "Failed to load project";
  }
  const fields = ((await callTool("list_custom_fields", {}).catch(() => ({}))) as CustomFieldsResult);
  const customFields = fields.fields ?? fields.custom_fields ?? [];

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="font-mono">{key}</span>
          {project?.project_type_key && <Badge variant="outline">{project.project_type_key}</Badge>}
        </div>
        <h1 className="text-2xl font-semibold">{project?.name ?? key}</h1>
      </div>

      {projectError ? (
        <Card>
          <CardHeader>
            <CardTitle>Could not load project</CardTitle>
            <CardDescription>{projectError}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
              <CardDescription>From the get_project MCP tool.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Lead</span>
                <span>{project?.lead?.display_name ?? "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Lead email</span>
                <span>{project?.lead?.email_address ?? "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Internal id</span>
                <span className="font-mono">{project?.id ?? "-"}</span>
              </div>
              {project?.description && (
                <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{project.description}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Quick actions</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              <Link className="hover:underline" href={`/issues?jql=${encodeURIComponent(`project = ${key} ORDER BY updated DESC`)}`}>
                Browse issues in this project
              </Link>
              <Link className="hover:underline" href={`/analytics?project=${key}`}>
                View analytics for this project
              </Link>
              <Link className="hover:underline" href="/issues/new">
                Create a new issue
              </Link>
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Custom fields</CardTitle>
          <CardDescription>Tenant-wide custom field configuration ({customFields.length}).</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-32">Id</TableHead>
                <TableHead>Name</TableHead>
                <TableHead className="w-40">Type</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {customFields.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-center text-muted-foreground">
                    No custom fields exposed by the MCP server.
                  </TableCell>
                </TableRow>
              ) : (
                customFields.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="font-mono text-xs">{f.id}</TableCell>
                    <TableCell>{f.name}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{f.type ?? "-"}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
