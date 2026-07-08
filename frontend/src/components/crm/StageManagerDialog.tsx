"use client";

import { useState } from "react";
import { ArrowUp, ArrowDown, Trash2, Plus, GripVertical } from "lucide-react";
import { cn } from "@/lib/utils";
import { CRMPipeline, CRMPipelineStage, CRMStageType } from "@/lib/api";
import { ColorPicker, STATUS_COLORS } from "./ColorPicker";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const COLORS = STATUS_COLORS.map((c) => c.color);
const STAGE_TYPES: { value: CRMStageType; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
];

interface StageManagerDialogProps {
  isOpen: boolean;
  onClose: () => void;
  pipeline: CRMPipeline;
  onCreateStage: (data: {
    name: string;
    color?: string;
    stage_type?: CRMStageType;
    probability?: number;
  }) => Promise<unknown> | void;
  onUpdateStage: (
    stageId: string,
    data: Partial<{ name: string; color: string; stage_type: CRMStageType; probability: number }>
  ) => Promise<unknown> | void;
  onDeleteStage: (stageId: string, reassignTo: string | null) => Promise<unknown> | void;
  onReorder: (stageIds: string[]) => Promise<unknown> | void;
}

export function StageManagerDialog({
  isOpen,
  onClose,
  pipeline,
  onCreateStage,
  onUpdateStage,
  onDeleteStage,
  onReorder,
}: StageManagerDialogProps) {
  const stages = [...(pipeline.stages || [])].sort((a, b) => a.position - b.position);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(COLORS[0]);
  const [deleting, setDeleting] = useState<CRMPipelineStage | null>(null);
  const [reassignTo, setReassignTo] = useState<string>("");

  const move = (index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= stages.length) return;
    const ids = stages.map((s) => s.id);
    [ids[index], ids[next]] = [ids[next], ids[index]];
    onReorder(ids);
  };

  const addStage = () => {
    if (!newName.trim()) return;
    onCreateStage({ name: newName.trim(), color: newColor, stage_type: "open" });
    setNewName("");
  };

  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Manage stages — {pipeline.name}</DialogTitle>
        </DialogHeader>

        <div className="space-y-2 max-h-[50vh] overflow-y-auto py-2">
          {stages.map((stage, i) => (
            <div
              key={stage.id}
              className="flex items-center gap-2 rounded-lg border border-border/40 p-2"
            >
              <GripVertical className="h-4 w-4 text-muted-foreground shrink-0" />
              <ColorPicker
                value={stage.color || COLORS[0]}
                onChange={(color) => onUpdateStage(stage.id, { color })}
                colors={COLORS}
                size="sm"
                className="shrink-0"
              />
              <Input
                defaultValue={stage.name}
                onBlur={(e) => {
                  if (e.target.value.trim() && e.target.value !== stage.name) {
                    onUpdateStage(stage.id, { name: e.target.value.trim() });
                  }
                }}
                className="h-8 flex-1"
              />
              <select
                value={stage.stage_type}
                onChange={(e) =>
                  onUpdateStage(stage.id, { stage_type: e.target.value as CRMStageType })
                }
                className="h-8 rounded-md border border-border/40 bg-background px-2 text-sm"
              >
                {STAGE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1 shrink-0">
                <Input
                  type="number"
                  min={0}
                  max={100}
                  defaultValue={stage.probability}
                  onBlur={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!Number.isNaN(v) && v !== stage.probability) {
                      onUpdateStage(stage.id, { probability: Math.max(0, Math.min(100, v)) });
                    }
                  }}
                  className="h-8 w-16"
                  title="Win probability %"
                />
                <span className="text-xs text-muted-foreground">%</span>
              </div>
              <div className="flex shrink-0">
                <button
                  onClick={() => move(i, -1)}
                  disabled={i === 0}
                  className="p-1 text-muted-foreground hover:text-foreground disabled:opacity-30"
                >
                  <ArrowUp className="h-4 w-4" />
                </button>
                <button
                  onClick={() => move(i, 1)}
                  disabled={i === stages.length - 1}
                  className="p-1 text-muted-foreground hover:text-foreground disabled:opacity-30"
                >
                  <ArrowDown className="h-4 w-4" />
                </button>
                <button
                  onClick={() => {
                    setDeleting(stage);
                    const fallback = stages.find((s) => s.id !== stage.id);
                    setReassignTo(fallback?.value_key || "");
                  }}
                  className="p-1 text-muted-foreground hover:text-red-500"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Add stage */}
        <div className="flex items-center gap-2 border-t border-border/40 pt-3">
          <ColorPicker value={newColor} onChange={setNewColor} colors={COLORS} size="sm" />
          <Input
            placeholder="New stage name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addStage()}
            className="h-8 flex-1"
          />
          <Button size="sm" onClick={addStage} disabled={!newName.trim()}>
            <Plus className="h-4 w-4 mr-1" /> Add
          </Button>
        </div>

        {/* Delete confirmation with reassignment */}
        {deleting && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-3 space-y-2">
            <p className="text-sm">
              Delete <strong>{deleting.name}</strong>? Move its records to:
            </p>
            <select
              value={reassignTo}
              onChange={(e) => setReassignTo(e.target.value)}
              className="h-8 w-full rounded-md border border-border/40 bg-background px-2 text-sm"
            >
              <option value="">— Clear stage —</option>
              {stages
                .filter((s) => s.id !== deleting.id)
                .map((s) => (
                  <option key={s.id} value={s.value_key}>
                    {s.name}
                  </option>
                ))}
            </select>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setDeleting(null)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={async () => {
                  await onDeleteStage(deleting.id, reassignTo || null);
                  setDeleting(null);
                }}
              >
                Delete stage
              </Button>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
