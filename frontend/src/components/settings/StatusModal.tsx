"use client";

import { useState } from "react";
import { AlertCircle, Check, RefreshCw } from "lucide-react";

import { StatusCategory, TaskStatusConfig } from "@/lib/api";

const STATUS_CATEGORIES: { value: StatusCategory; label: string; color: string }[] = [
  { value: "todo", label: "To Do", color: "bg-blue-500" },
  { value: "in_progress", label: "In Progress", color: "bg-yellow-500" },
  { value: "done", label: "Done", color: "bg-green-500" },
];

const PRESET_COLORS = [
  "#6B7280",
  "#EF4444",
  "#F59E0B",
  "#10B981",
  "#3B82F6",
  "#8B5CF6",
  "#EC4899",
  "#14B8A6",
  "#F97316",
  "#6366F1",
];

export interface StatusModalProps {
  status: TaskStatusConfig | null;
  onClose: () => void;
  onSave: (data: {
    name: string;
    category: StatusCategory;
    color: string;
    icon?: string;
    is_default?: boolean;
  }) => Promise<void>;
  isSaving: boolean;
}

export function StatusModal({ status, onClose, onSave, isSaving }: StatusModalProps) {
  const [name, setName] = useState(status?.name || "");
  const [category, setCategory] = useState<StatusCategory>(status?.category || "todo");
  const [color, setColor] = useState(status?.color || "#6B7280");
  const [isDefault, setIsDefault] = useState(status?.is_default || false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Status name is required");
      return;
    }
    try {
      await onSave({ name: name.trim(), category, color, is_default: isDefault });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save status");
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-xl w-full max-w-md p-6">
        <h3 className="text-xl font-semibold text-foreground mb-4">
          {status ? "Edit Status" : "Create Status"}
        </h3>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-muted-foreground mb-1">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="In Review"
                className="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary-500"
              />
            </div>

            <div>
              <label className="block text-sm text-muted-foreground mb-1">Category</label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {STATUS_CATEGORIES.map((cat) => (
                  <button
                    key={cat.value}
                    type="button"
                    onClick={() => setCategory(cat.value)}
                    className={`p-2 rounded-lg border text-center transition ${
                      category === cat.value
                        ? "border-primary-500 bg-primary-900/20"
                        : "border-border hover:border-border"
                    }`}
                  >
                    <div className={`w-3 h-3 ${cat.color} rounded-full mx-auto mb-1`} />
                    <span className="text-foreground text-sm">{cat.label}</span>
                  </button>
                ))}
              </div>
              <p className="text-muted-foreground text-xs mt-1">
                Category affects burndown chart calculations
              </p>
            </div>

            <div>
              <label className="block text-sm text-muted-foreground mb-1">Color</label>
              <div className="flex flex-wrap gap-2">
                {PRESET_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setColor(c)}
                    className={`w-8 h-8 rounded-lg border-2 transition ${
                      color === c ? "border-white" : "border-transparent"
                    }`}
                    style={{ backgroundColor: c }}
                  />
                ))}
                <input
                  type="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="w-8 h-8 rounded-lg cursor-pointer"
                />
              </div>
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="w-4 h-4 rounded border-border bg-muted text-primary-500 focus:ring-primary-500"
              />
              <span className="text-foreground text-sm">Set as default status for new tasks</span>
            </label>

            {error && (
              <div className="flex items-center gap-2 text-red-400 text-sm">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}
          </div>

          <div className="flex gap-3 mt-6">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-muted hover:bg-accent text-foreground rounded-lg transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="flex-1 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {isSaving ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Check className="h-4 w-4" />
                  Save
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
