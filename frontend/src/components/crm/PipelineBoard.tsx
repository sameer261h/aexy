"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Settings2, Plus, TrendingUp, BarChart3 } from "lucide-react";
import { CRMObject, CRMRecord } from "@/lib/api";
import { usePipelines, usePipelineAnalytics } from "@/hooks/usePipelines";
import { KanbanBoard } from "./KanbanBoard";
import { StageManagerDialog } from "./StageManagerDialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface PipelineBoardProps {
  workspaceId: string;
  object: CRMObject;
  records: CRMRecord[];
  onRecordClick?: (record: CRMRecord) => void;
  onRecordUpdate?: (recordId: string, values: Record<string, unknown>) => Promise<void>;
  onCreateInStage?: (stage: string) => void;
  highlightAttributes?: string[];
  isLoading?: boolean;
}

export function PipelineBoard({
  workspaceId,
  object,
  records,
  onRecordClick,
  onRecordUpdate,
  onCreateInStage,
  highlightAttributes = [],
  isLoading = false,
}: PipelineBoardProps) {
  const {
    pipelines,
    createPipeline,
    createStage,
    updateStage,
    deleteStage,
    reorderStages,
  } = usePipelines(workspaceId, object.id);

  const router = useRouter();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showStages, setShowStages] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newPipelineName, setNewPipelineName] = useState("");

  const activePipeline = useMemo(() => {
    if (!pipelines.length) return null;
    return (
      pipelines.find((p) => p.id === activeId) ||
      pipelines.find((p) => p.is_default) ||
      pipelines[0]
    );
  }, [pipelines, activeId]);

  const statusSlug = useMemo(() => {
    if (!activePipeline?.status_attribute_id) return undefined;
    return object.attributes?.find((a) => a.id === activePipeline.status_attribute_id)?.slug;
  }, [activePipeline, object.attributes]);

  const { forecast } = usePipelineAnalytics(workspaceId, activePipeline?.id || null);

  // No pipeline yet for this object — offer to create one.
  if (!activePipeline) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
        <p>No pipeline configured for {object.plural_name}.</p>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Create pipeline
        </Button>
        <CreatePipelineDialog
          open={showCreate}
          onClose={() => setShowCreate(false)}
          name={newPipelineName}
          setName={setNewPipelineName}
          onCreate={() => {
            createPipeline.mutate({ object_id: object.id, name: newPipelineName || "Pipeline" });
            setShowCreate(false);
            setNewPipelineName("");
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Pipeline toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={activePipeline.id}
          onChange={(e) => setActiveId(e.target.value)}
          className="h-9 rounded-md border border-border/40 bg-background px-3 text-sm font-medium"
        >
          {pipelines.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {p.is_default ? " (default)" : ""}
            </option>
          ))}
        </select>

        <Button variant="outline" size="sm" onClick={() => setShowStages(true)}>
          <Settings2 className="h-4 w-4 mr-1" /> Manage stages
        </Button>
        <Button variant="outline" size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> New pipeline
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push(`/crm/${object.slug}/pipeline`)}
        >
          <BarChart3 className="h-4 w-4 mr-1" /> Analytics
        </Button>

        {forecast.data && (
          <div className="ml-auto flex items-center gap-4 text-sm">
            <span className="flex items-center gap-1 text-muted-foreground">
              <TrendingUp className="h-4 w-4" />
              Weighted forecast:{" "}
              <strong className="text-foreground">
                ${Math.round(forecast.data.weighted_forecast).toLocaleString()}
              </strong>
            </span>
            <span className="text-muted-foreground">
              Open: {forecast.data.open_count} · $
              {Math.round(forecast.data.open_value).toLocaleString()}
            </span>
          </div>
        )}
      </div>

      <KanbanBoard
        records={records}
        attributes={object.attributes || []}
        statusAttribute={statusSlug}
        onRecordClick={onRecordClick}
        onRecordUpdate={onRecordUpdate}
        onCreateInStage={onCreateInStage}
        onAddStage={() => setShowStages(true)}
        highlightAttributes={highlightAttributes}
        isLoading={isLoading}
      />

      <StageManagerDialog
        isOpen={showStages}
        onClose={() => setShowStages(false)}
        pipeline={activePipeline}
        onCreateStage={(data) => createStage.mutate({ pipelineId: activePipeline.id, data })}
        onUpdateStage={(stageId, data) =>
          updateStage.mutate({ pipelineId: activePipeline.id, stageId, data })
        }
        onDeleteStage={(stageId, reassignTo) =>
          deleteStage.mutate({ pipelineId: activePipeline.id, stageId, reassignTo })
        }
        onReorder={(stageIds) => reorderStages.mutate({ pipelineId: activePipeline.id, stageIds })}
      />

      <CreatePipelineDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        name={newPipelineName}
        setName={setNewPipelineName}
        onCreate={() => {
          createPipeline.mutate({ object_id: object.id, name: newPipelineName || "Pipeline" });
          setShowCreate(false);
          setNewPipelineName("");
        }}
      />
    </div>
  );
}

function CreatePipelineDialog({
  open,
  onClose,
  name,
  setName,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  name: string;
  setName: (v: string) => void;
  onCreate: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New pipeline</DialogTitle>
        </DialogHeader>
        <Input
          placeholder="Pipeline name (e.g. Enterprise Sales)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onCreate()}
          autoFocus
        />
        <p className="text-xs text-muted-foreground">
          A new pipeline starts with default stages. You can rename, recolor, and reorder them
          from “Manage stages”.
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onCreate} disabled={!name.trim()}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
