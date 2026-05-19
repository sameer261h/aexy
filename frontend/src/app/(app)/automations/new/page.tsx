"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ChevronLeft, Loader2, Sparkles } from "lucide-react";
import { Node, Edge } from "@xyflow/react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { api, AutomationModule } from "@/lib/api";
import {
  AUTOMATION_TEMPLATES,
  AutomationTemplate,
  defaultTriggerTypes,
  getDefaultEdges,
  getDefaultNodes,
  moduleLabels,
} from "@/lib/automationTemplates";
import { TemplateGallery } from "@/components/automations/TemplateGallery";

// WorkflowCanvas drags in @xyflow/react + 7 node components (~150 KB). It
// only matters when the user actually opens the canvas — both the
// template gallery first-run path AND the early `if (!workspaceId)`
// skeleton avoid loading it. Lazy-import via dynamic() so the bundle
// only ships when we're sure we need it.
const WorkflowCanvas = dynamic(
  () => import("@/components/workflow-builder").then((m) => m.WorkflowCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        Loading canvas...
      </div>
    ),
  },
);

export default function NewAutomationPage() {
  const t = useTranslations("automations");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { currentWorkspace } = useWorkspace();

  // Get module and template from URL query params.
  const moduleParam = searchParams.get("module") as AutomationModule | null;
  const templateParam = searchParams.get("template");
  const startBlank = searchParams.get("blank") === "1";
  const template = templateParam ? AUTOMATION_TEMPLATES[templateParam] : null;

  // Decide whether to show the gallery or the canvas. The audit flagged
  // the blank-canvas cold-start as a major UX cliff; we now route
  // first-time creators through a template picker unless they
  // explicitly opted to skip (?blank=1) or arrived with a template
  // already picked.
  const showCanvas = !!template || startBlank;

  const [module, setModule] = useState<AutomationModule>(
    template?.module || moduleParam || "crm"
  );
  const [name, setName] = useState(template?.name || "New Automation");
  const [description, setDescription] = useState(template?.description || "");
  const [isCreating, setIsCreating] = useState(false);
  const [automationId, setAutomationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleUseTemplate = (picked: AutomationTemplate) => {
    const params = new URLSearchParams();
    params.set("template", picked.id);
    if (moduleParam && moduleParam !== picked.module) {
      // Keep the originating module-filter on the URL so the back button
      // returns to that filtered list.
      params.set("module", moduleParam);
    }
    router.replace(`/automations/new?${params.toString()}`);
  };

  const handleStartBlank = () => {
    const params = new URLSearchParams();
    params.set("blank", "1");
    if (moduleParam) params.set("module", moduleParam);
    router.replace(`/automations/new?${params.toString()}`);
  };

  const workspaceId = currentWorkspace?.id;

  const handleCreateAutomation = useCallback(async () => {
    if (!workspaceId || isCreating) return null;

    setIsCreating(true);
    setError(null);

    try {
      // Use the correct default trigger type for the module
      const defaultTrigger = defaultTriggerTypes[module] || defaultTriggerTypes.crm;
      const response = await api.post(`/workspaces/${workspaceId}/automations`, {
        name,
        description,
        module,
        trigger_type: defaultTrigger.type,
        trigger_config: {},
        actions: [], // Start with empty actions, user will add via workflow canvas
      });
      setAutomationId(response.data.id);
      return response.data.id;
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "Failed to create automation";
      setError(errorMessage);
      return null;
    } finally {
      setIsCreating(false);
    }
  }, [workspaceId, name, description, module, isCreating]);

  const handleSave = useCallback(
    async (nodes: Node[], edges: Edge[], viewport: { x: number; y: number; zoom: number }) => {
      if (!workspaceId) return;

      let currentAutomationId = automationId;

      // Extract trigger type from the trigger node
      const triggerNode = nodes.find((n) => n.type === "trigger");
      const triggerType = (triggerNode?.data?.trigger_type as string) || "record.created";
      
      // Create automation if not exists
      if (!currentAutomationId) {
        currentAutomationId = await handleCreateAutomation();
        if (!currentAutomationId) return;
      }

      // Update workflow (workflow endpoints are under /crm/automations)
      try {
        await api.put(
          `/workspaces/${workspaceId}/crm/automations/${currentAutomationId}/workflow`,
          {
            nodes,
            edges,
            viewport,
          }
        );

        // Also update the automation's trigger_type to match the trigger node
        await api.patch(
          `/workspaces/${workspaceId}/automations/${currentAutomationId}`,
          {
            trigger_type: triggerType,
          }
        );
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : "Failed to save workflow";
        setError(errorMessage);
      }
    },
    [workspaceId, automationId, handleCreateAutomation]
  );

  const handlePublish = useCallback(async () => {
    if (!workspaceId || !automationId) return;

    try {
      await api.post(
        `/workspaces/${workspaceId}/crm/automations/${automationId}/workflow/publish`
      );
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "Failed to publish workflow";
      setError(errorMessage);
    }
  }, [workspaceId, automationId]);

  const handleUnpublish = useCallback(async () => {
    if (!workspaceId || !automationId) return;

    try {
      await api.post(
        `/workspaces/${workspaceId}/crm/automations/${automationId}/workflow/unpublish`
      );
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "Failed to unpublish workflow";
      setError(errorMessage);
    }
  }, [workspaceId, automationId]);

  const handleTest = useCallback(
    async (recordId?: string) => {
      if (!workspaceId || !automationId) return;

      try {
        const response = await api.post(
          `/workspaces/${workspaceId}/crm/automations/${automationId}/workflow/execute`,
          {
            dry_run: true,
            // Only include record_id if provided and non-empty
            ...(recordId?.trim() ? { record_id: recordId.trim() } : {}),
          }
        );
        console.log("Test execution result:", response.data);
        return response.data;
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : "Failed to test workflow";
        setError(errorMessage);
      }
    },
    [workspaceId, automationId]
  );

  const handleBack = () => {
    const backUrl = moduleParam ? `/automations?module=${moduleParam}` : "/automations";
    router.push(backUrl);
  };

  if (!workspaceId) {
    return (
      <div className="min-h-screen bg-background animate-pulse">
        <div className="h-[calc(100vh-64px)] flex flex-col">
          <div className="flex items-center justify-between gap-4 px-4 py-3 border-b border-border bg-muted/50">
            <div className="flex items-center gap-4">
              <div className="h-9 w-9 bg-accent rounded-lg" />
              <div>
                <div className="h-5 w-48 bg-accent rounded mb-2" />
                <div className="h-3 w-32 bg-accent rounded" />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-9 w-20 bg-accent rounded-lg" />
              <div className="h-9 w-24 bg-accent rounded-lg" />
            </div>
          </div>
          <div className="flex-1 flex">
            <div className="flex-1 p-6 space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="bg-muted border border-border rounded-xl p-4">
                  <div className="h-4 w-32 bg-accent rounded mb-3" />
                  <div className="h-10 w-full bg-accent rounded-lg" />
                </div>
              ))}
            </div>
            <div className="w-80 border-l border-border p-4 space-y-3">
              <div className="h-4 w-24 bg-accent rounded" />
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-10 w-full bg-accent rounded-lg" />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Gallery mode — no template + user hasn't explicitly opted to skip.
  if (!showCanvas) {
    return (
      <TemplateGallery
        initialModule={moduleParam}
        onUseTemplate={handleUseTemplate}
        onStartBlank={handleStartBlank}
        onBack={handleBack}
      />
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="h-[calc(100vh-64px)] flex flex-col">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 px-4 py-3 border-b border-border bg-muted/50 relative z-10">
          <div className="flex items-center gap-4">
            <button
              onClick={handleBack}
              className="p-2 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition-colors"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            <div>
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="text-lg font-semibold text-foreground bg-transparent border-none focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded px-2 py-1 -ml-2"
                  placeholder={t("builder.namePlaceholder")}
                />
                <select
                  value={module}
                  onChange={(e) => setModule(e.target.value as AutomationModule)}
                  className="text-sm bg-accent border border-border rounded-lg px-3 py-1 text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                >
                  {Object.entries(moduleLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="block text-sm text-muted-foreground bg-transparent border-none focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded px-2 py-0.5 -ml-2 w-full max-w-md"
                placeholder={t("builder.descriptionPlaceholder")}
              />
            </div>
          </div>

          {error && (
            <div className="text-red-400 text-sm bg-red-500/10 px-3 py-1 rounded-lg">
              {error}
            </div>
          )}
        </div>

        {/* Template Banner — anchors the canvas to the template the user
            just picked, with a one-click escape back to the gallery in
            case they want to try a different starting point. */}
        {template && (
          <div className="flex items-center gap-2 px-4 py-2 bg-primary/5 border-b border-primary/20 text-sm">
            <Sparkles className="h-4 w-4 text-primary shrink-0" />
            <span className="text-muted-foreground flex-1">
              {t("builder.fromTemplate")}
              {" "}
              <span className="text-foreground font-medium">{template.name}</span>
              {" "}
              {t("builder.fromTemplateTail")}
            </span>
            <Link
              href={moduleParam ? `/automations/new?module=${moduleParam}` : "/automations/new"}
              className="text-primary hover:underline text-xs font-medium"
            >
              {t("builder.pickAnotherTemplate")}
            </Link>
          </div>
        )}

        {/* Workflow Canvas */}
        <div className="flex-1">
          <WorkflowCanvas
            key={module}  // Force re-render when module changes
            automationId={automationId || "new"}
            workspaceId={workspaceId}
            module={module}
            initialNodes={getDefaultNodes(module, template)}
            initialEdges={getDefaultEdges(template)}
            onSave={handleSave}
            onPublish={handlePublish}
            onUnpublish={handleUnpublish}
            onTest={handleTest}
          />
        </div>
      </div>
    </div>
  );
}
