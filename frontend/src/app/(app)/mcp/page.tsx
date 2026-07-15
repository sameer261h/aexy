"use client";

import { useState } from "react";
import {
  Plug,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  KeyRound,
  Terminal,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { CopyButton } from "@/components/ui/copy-button";

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="relative group">
      <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <CopyButton text={code} />
      </div>
      <pre className="bg-zinc-900 border border-border rounded-lg p-4 overflow-x-auto text-sm">
        <code className="text-zinc-300">{code}</code>
      </pre>
    </div>
  );
}

/**
 * Hand-maintained catalog of MCP tools exposed on this docs page.
 *
 * SOURCE OF TRUTH: the external MCP server repo
 * https://github.com/aexy-io/mcp-server
 *
 * This list is NOT generated — it duplicates the tools defined in that repo
 * for display purposes only. Whenever tools are added, removed, or renamed in
 * mcp-server, update this array (tool identifier) AND the matching i18n keys
 * in messages/{en,hi}/mcp.json under `categories.<category>.tools.<identifier>`.
 *
 * Category keys and tool identifiers are stable and map directly to i18n keys.
 * Human-readable category names and tool descriptions live in i18n, not here.
 */
const TOOL_CATEGORIES: { key: string; tools: string[] }[] = [
  {
    key: "sprintManagement",
    tools: [
      "aexy_sprints",
      "aexy_sprint_tasks",
      "aexy_sprint_analytics",
      "aexy_projects",
      "aexy_epics",
      "aexy_bugs",
    ],
  },
  {
    key: "crm",
    tools: ["aexy_crm_objects", "aexy_crm_records", "aexy_crm_automations"],
  },
  {
    key: "aiAgents",
    tools: ["aexy_agents", "aexy_agent_policies", "aexy_workflows"],
  },
  {
    key: "emailGtm",
    tools: [
      "aexy_email_campaigns",
      "aexy_email_infrastructure",
      "aexy_gtm_leads",
      "aexy_gtm_sequences",
    ],
  },
  {
    key: "analyticsInsights",
    tools: [
      "aexy_analytics",
      "aexy_developer_insights",
      "aexy_compliance",
      "aexy_assessments",
    ],
  },
  {
    key: "platform",
    tools: [
      "aexy_workspaces",
      "aexy_notifications",
      "aexy_documents",
      "aexy_tickets",
      "aexy_tables",
      "aexy_integrations",
      "aexy_api",
    ],
  },
  {
    key: "temporal",
    tools: [
      "temporal_list_workflows",
      "temporal_describe_workflow",
      "temporal_get_workflow_history",
      "temporal_query_workflow",
      "temporal_signal_workflow",
      "temporal_cancel_workflow",
      "temporal_list_schedules",
      "temporal_system_status",
    ],
  },
];

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getClaudeConfig(apiUrl: string) {
  return `{
  "mcpServers": {
    "aexy": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/aexy/mcp-server", "aexy-mcp"],
      "env": {
        "AEXY_API_URL": "${apiUrl}",
        "AEXY_API_TOKEN": "<your-api-token>",
        "AEXY_ENABLE_TEMPORAL": "true"
      }
    }
  }
}`;
}

function getGenericConfig(apiUrl: string) {
  return `# Environment variables for the MCP server
export AEXY_API_URL="${apiUrl}"
export AEXY_API_TOKEN="<your-api-token>"
export AEXY_ENABLE_TEMPORAL="true"
export TEMPORAL_ADDRESS="localhost:7233"
export TEMPORAL_NAMESPACE="default"

# Run the MCP server via stdio
uv run --directory /path/to/aexy/mcp-server aexy-mcp`;
}

type ClientTab = "claude" | "codex" | "other";

function ToolCategory({
  categoryKey,
  tools,
}: {
  categoryKey: string;
  tools: string[];
}) {
  const t = useTranslations("mcp");
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-border rounded-lg">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-accent/50 transition-colors rounded-lg"
      >
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">
            {t(`categories.${categoryKey}.name`)}
          </span>
          <span className="text-xs text-muted-foreground bg-accent px-1.5 py-0.5 rounded">
            {tools.length}
          </span>
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {open && (
        <div className="px-4 pb-3 space-y-1">
          {tools.map((tool) => (
            <div key={tool} className="flex items-start gap-3 py-1.5 text-sm">
              <code className="text-xs bg-accent px-1.5 py-0.5 rounded font-mono text-foreground shrink-0">
                {tool}
              </code>
              <span className="text-muted-foreground">
                {t(`categories.${categoryKey}.tools.${tool}`)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function McpPage() {
  const t = useTranslations("mcp");
  const [activeTab, setActiveTab] = useState<ClientTab>("claude");

  const totalTools = TOOL_CATEGORIES.reduce(
    (sum, cat) => sum + cat.tools.length,
    0
  );

  return (
    <div className="max-w-4xl mx-auto px-6 py-8 space-y-10">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-3">
          <div className="h-10 w-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
            <Plug className="h-5 w-5 text-purple-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">{t("title")}</h1>
            <p className="text-muted-foreground text-sm">{t("subtitle")}</p>
          </div>
        </div>
      </div>

      {/* Overview */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">{t("overview.heading")}</h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {t("overview.descriptionBefore")}
          <a
            href="https://modelcontextprotocol.io"
            target="_blank"
            rel="noopener noreferrer"
            className="text-purple-400 hover:underline"
          >
            {t("overview.linkText")}
          </a>
          {t("overview.descriptionAfter")}
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {TOOL_CATEGORIES.map((cat) => (
            <div
              key={cat.key}
              className="bg-accent/50 border border-border rounded-lg px-3 py-2"
            >
              <div className="text-sm font-medium">
                {t(`categories.${cat.key}.name`)}
              </div>
              <div className="text-xs text-muted-foreground">
                {t("overview.toolCount", { count: cat.tools.length })}
              </div>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {t("overview.summary", {
            total: totalTools,
            categories: TOOL_CATEGORIES.length,
          })}
        </p>
      </section>

      {/* Quick Start */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">{t("quickStart.heading")}</h2>
        <div className="space-y-4">
          <div className="flex gap-3">
            <div className="flex-shrink-0 h-6 w-6 rounded-full bg-purple-500/20 text-purple-400 flex items-center justify-center text-xs font-bold">
              1
            </div>
            <div className="space-y-1">
              <p className="text-sm font-medium">
                {t("quickStart.step1.title")}
              </p>
              <p className="text-sm text-muted-foreground">
                {t("quickStart.step1.description")}
              </p>
              <Link
                href="/settings/api-tokens"
                className="inline-flex items-center gap-1.5 text-sm text-purple-400 hover:underline"
              >
                <KeyRound className="h-3.5 w-3.5" />
                {t("quickStart.step1.link")}
                <ExternalLink className="h-3 w-3" />
              </Link>
            </div>
          </div>
          <div className="flex gap-3">
            <div className="flex-shrink-0 h-6 w-6 rounded-full bg-purple-500/20 text-purple-400 flex items-center justify-center text-xs font-bold">
              2
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium">
                {t("quickStart.step2.title")}
              </p>
              <CodeBlock code="git clone https://github.com/aexy-io/mcp-server.git && cd mcp-server && uv sync" />
            </div>
          </div>
          <div className="flex gap-3">
            <div className="flex-shrink-0 h-6 w-6 rounded-full bg-purple-500/20 text-purple-400 flex items-center justify-center text-xs font-bold">
              3
            </div>
            <div>
              <p className="text-sm font-medium">
                {t("quickStart.step3.title")}
              </p>
              <p className="text-sm text-muted-foreground">
                {t("quickStart.step3.description")}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Client Setup Guides */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">{t("clientSetup.heading")}</h2>
        <div className="flex gap-1 border-b border-border">
          {(
            [
              { id: "claude" as const, label: t("clientSetup.tabs.claude") },
              { id: "codex" as const, label: t("clientSetup.tabs.codex") },
              { id: "other" as const, label: t("clientSetup.tabs.other") },
            ] as const
          ).map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-purple-400 text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {activeTab === "claude" && (
            <>
              <p className="text-sm text-muted-foreground">
                {t("clientSetup.claude.introBefore")}
                <code className="text-xs bg-accent px-1 py-0.5 rounded">
                  .claude/settings.local.json
                </code>
                {t("clientSetup.claude.introAfter")}
              </p>
              <CodeBlock code={getClaudeConfig(API_BASE)} />
              <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-3">
                <p className="text-xs text-muted-foreground">
                  <strong className="text-foreground">
                    {t("clientSetup.claude.noteLabel")}
                  </strong>
                  {t("clientSetup.claude.noteBefore")}
                  <code className="bg-accent px-1 py-0.5 rounded">
                    AEXY_ENABLE_TEMPORAL
                  </code>
                  {t("clientSetup.claude.noteMiddle")}
                  <code className="bg-accent px-1 py-0.5 rounded">false</code>
                  {t("clientSetup.claude.noteAfter")}
                </p>
              </div>
            </>
          )}

          {activeTab === "codex" && (
            <>
              <p className="text-sm text-muted-foreground">
                {t("clientSetup.codex.intro")}
              </p>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">
                    {t("clientSetup.codex.serverCommand")}
                  </span>
                </div>
                <CodeBlock
                  code={`uv run --directory /path/to/aexy/mcp-server aexy-mcp`}
                />
              </div>
              <div className="space-y-2">
                <span className="text-sm font-medium">
                  {t("clientSetup.codex.requiredEnvVars")}
                </span>
                <div className="bg-accent/50 border border-border rounded-lg divide-y divide-border text-sm">
                  {[
                    [
                      "AEXY_API_URL",
                      API_BASE,
                      t("clientSetup.codex.env.apiUrl"),
                    ],
                    [
                      "AEXY_API_TOKEN",
                      "<your-token>",
                      t("clientSetup.codex.env.apiToken"),
                    ],
                    [
                      "AEXY_ENABLE_TEMPORAL",
                      "true",
                      t("clientSetup.codex.env.enableTemporal"),
                    ],
                  ].map(([name, value, desc]) => (
                    <div
                      key={name}
                      className="flex items-center px-3 py-2 gap-4"
                    >
                      <code className="font-mono text-xs text-foreground w-48 shrink-0">
                        {name}
                      </code>
                      <code className="font-mono text-xs text-muted-foreground flex-1">
                        {value}
                      </code>
                      <span className="text-xs text-muted-foreground">
                        {desc}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {activeTab === "other" && (
            <>
              <p className="text-sm text-muted-foreground">
                {t("clientSetup.other.intro")}
              </p>
              <CodeBlock code={getGenericConfig(API_BASE)} />
              <div className="bg-accent/50 border border-border rounded-lg p-3">
                <p className="text-xs text-muted-foreground">
                  <strong className="text-foreground">
                    {t("clientSetup.other.envReferenceLabel")}
                  </strong>
                </p>
                <div className="mt-2 space-y-1 text-xs">
                  {[
                    ["AEXY_API_URL", t("clientSetup.other.env.apiUrl")],
                    ["AEXY_API_TOKEN", t("clientSetup.other.env.apiToken")],
                    [
                      "AEXY_ENABLE_TEMPORAL",
                      t("clientSetup.other.env.enableTemporal"),
                    ],
                    [
                      "TEMPORAL_ADDRESS",
                      t("clientSetup.other.env.temporalAddress"),
                    ],
                    [
                      "TEMPORAL_NAMESPACE",
                      t("clientSetup.other.env.temporalNamespace"),
                    ],
                  ].map(([name, desc]) => (
                    <div key={name} className="flex gap-2">
                      <code className="font-mono text-foreground shrink-0">
                        {name}
                      </code>
                      <span className="text-muted-foreground">{desc}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </section>

      {/* Available Tools */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">
          {t("availableTools.heading")}
        </h2>
        <div className="space-y-2">
          {TOOL_CATEGORIES.map((cat) => (
            <ToolCategory
              key={cat.key}
              categoryKey={cat.key}
              tools={cat.tools}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
