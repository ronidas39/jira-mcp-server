import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";
import { AppSidebar } from "@/components/app-sidebar";

export const metadata: Metadata = {
  title: "Jira MCP Console",
  description: "Drive the Jira MCP server from a web console.",
};

export default function RootLayout({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background antialiased">
        <Providers>
          <div className="flex min-h-screen w-full">
            <AppSidebar />
            <main className="flex min-h-screen w-full flex-col">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
