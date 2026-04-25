import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { callTool } from "@/lib/mcp-client";

export const dynamic = "force-dynamic";

interface ListProjectsResult {
  projects: Array<{ key: string; id?: string; name: string; project_type_key?: string; lead?: { display_name?: string } | null }>;
}

export default async function ProjectsPage(): Promise<React.ReactElement> {
  let projects: ListProjectsResult["projects"] = [];
  let errorMessage: string | null = null;
  try {
    const result = (await callTool("list_projects", {})) as ListProjectsResult;
    projects = result.projects ?? [];
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : "Failed to load projects";
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Projects</h1>
        <p className="text-sm text-muted-foreground">All projects visible to the configured Jira account.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Project list</CardTitle>
          <CardDescription>
            {errorMessage ? errorMessage : `${projects.length} projects.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-32">Key</TableHead>
                <TableHead>Name</TableHead>
                <TableHead className="w-32">Type</TableHead>
                <TableHead className="w-48">Lead</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {projects.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground">
                    No projects found.
                  </TableCell>
                </TableRow>
              ) : (
                projects.map((p) => (
                  <TableRow key={p.key}>
                    <TableCell className="font-mono text-xs">
                      <Link href={`/projects/${p.key}`} className="hover:underline">
                        {p.key}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Link href={`/projects/${p.key}`} className="hover:underline">
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{p.project_type_key ?? "-"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{p.lead?.display_name ?? "-"}</TableCell>
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
