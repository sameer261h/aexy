"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  Plus,
  ChevronLeft,
  Trash2,
  Building2,
  Users,
  DollarSign,
  LayoutGrid,
  Target,
  Settings,
} from "lucide-react";
import { SearchInput } from "@/components/ui/search-input";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useAuth } from "@/hooks/useAuth";
import { useCRMObjects, useCRMRecords } from "@/hooks/useCRM";
import { useSavedViews } from "@/hooks/useTables";
import { CRMObject, CRMRecord, CRMAttribute, CRMAttributeType, CRMObjectType, TableSavedView, ColumnDisplayConfig } from "@/lib/api";
import { ViewSwitcher, ViewMode } from "@/components/crm/ViewSwitcher";
import { SavedViewSwitcher } from "@/components/crm/SavedViewSwitcher";
import { DataTable } from "@/components/crm/DataTable";
import { KanbanBoard } from "@/components/crm/KanbanBoard";
import { PipelineBoard } from "@/components/crm/PipelineBoard";
import { ColumnVisibilityMenu } from "@/components/crm/ColumnSelector";
import { FieldEditor } from "@/components/fields";
import { TableFilterPanel, FilterRule } from "@/components/tables";

const PAGE_LIMIT = 50;
const SEARCH_DEBOUNCE_MS = 300;

const CONNECTION_STRENGTH_OPTIONS = [
  { value: "weak", label: "Weak", color: "#f59e0b" },
  { value: "good", label: "Good", color: "#3b82f6" },
  { value: "strong", label: "Strong", color: "#3b82f6" },
  { value: "very_strong", label: "Very Strong", color: "#22c55e" },
];

function synthesizeComputedAttributes(): CRMAttribute[] {
  const base: Omit<CRMAttribute, "id" | "object_id"> = {
    name: "",
    slug: "",
    attribute_type: "text",
    description: null,
    is_required: false,
    is_unique: false,
    is_searchable: false,
    is_filterable: false,
    is_sortable: false,
    is_system: true,
    config: {},
    default_value: null,
    order: 0,
    created_at: "",
    updated_at: "",
  };
  return [
    {
      ...base,
      id: "__sys_last_email_interaction",
      object_id: "",
      name: "Last email interaction",
      slug: "__last_email_interaction",
      attribute_type: "timestamp" as CRMAttributeType,
      config: {},
    },
    {
      ...base,
      id: "__sys_last_calendar_interaction",
      object_id: "",
      name: "Last calendar interaction",
      slug: "__last_calendar_interaction",
      attribute_type: "timestamp" as CRMAttributeType,
      config: {},
    },
    {
      ...base,
      id: "__sys_connection_strength",
      object_id: "",
      name: "Connection strength",
      slug: "__connection_strength",
      attribute_type: "status",
      config: { options: CONNECTION_STRENGTH_OPTIONS },
    },
  ];
}

export function applyPersonComputedColumns(
  records: CRMRecord[],
  attributes: CRMAttribute[],
  objectType: string,
): { records: CRMRecord[]; attributes: CRMAttribute[] } {
  if (objectType !== "person") {
    return { records, attributes };
  }

  const synthesizedAttrs = synthesizeComputedAttributes();

  const updatedRecords = records.map((record) => {
    const values = { ...record.values };
    values.__last_email_interaction = record.computed?.last_email_interaction ?? null;
    values.__last_calendar_interaction = record.computed?.last_calendar_interaction ?? null;
    values.__connection_strength = record.computed?.connection_strength ?? null;
    return { ...record, values };
  });

  return {
    records: updatedRecords,
    attributes: [...attributes, ...synthesizedAttrs],
  };
}

// FilterRule uses a UI-only checkbox shorthand (is_true/is_false) that the
// backend query contract doesn't have; equals/"true"|"false" round-trips it.
function toQueryFilters(rules: FilterRule[]): Record<string, unknown>[] {
  return rules
    .filter((r) => r.field && (r.value !== "" || r.operator === "is_empty" || r.operator === "is_not_empty" || r.operator === "is_true" || r.operator === "is_false"))
    .map((r) => {
      if (r.operator === "is_true") return { attribute: r.field, operator: "equals", value: "true" };
      if (r.operator === "is_false") return { attribute: r.field, operator: "equals", value: "false" };
      return { attribute: r.field, operator: r.operator, value: r.value };
    });
}

function fromQueryFilters(saved: Record<string, unknown>[] | undefined): FilterRule[] {
  if (!saved?.length) return [];
  return saved.map((f, idx) => {
    const attribute = String(f.attribute ?? "");
    const operator = String(f.operator ?? "equals");
    const value = f.value;
    if (operator === "equals" && value === "true") {
      return { id: `restored_${idx}_${Date.now()}`, field: attribute, operator: "is_true", value: "" };
    }
    if (operator === "equals" && value === "false") {
      return { id: `restored_${idx}_${Date.now()}`, field: attribute, operator: "is_false", value: "" };
    }
    return {
      id: `restored_${idx}_${Date.now()}`,
      field: attribute,
      operator: operator as FilterRule["operator"],
      value: value == null ? "" : String(value),
    };
  });
}

const objectTypeIcons: Record<CRMObjectType, React.ReactNode> = {
  company: <Building2 className="h-5 w-5" />,
  person: <Users className="h-5 w-5" />,
  deal: <DollarSign className="h-5 w-5" />,
  lead: <Target className="h-5 w-5" />,
  custom: <LayoutGrid className="h-5 w-5" />,
};

function tableAttributes(attributes: CRMAttribute[] = []) {
  return attributes.filter(
    (attr) => attr.slug !== "name" && (attr.slug.startsWith("__") || !attr.is_system),
  );
}

function CreateRecordModal({
  isOpen,
  onClose,
  onCreate,
  isCreating,
  object,
  defaultValues,
}: {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (values: Record<string, unknown>) => Promise<void>;
  isCreating: boolean;
  object: CRMObject;
  defaultValues?: Record<string, unknown>;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(defaultValues || {});

  useEffect(() => {
    if (defaultValues) {
      setValues(defaultValues);
    }
  }, [defaultValues]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onCreate(values);
    setValues({});
    onClose();
  };

  const editableAttributes = object.attributes?.filter((attr) => !attr.is_system) || [];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-muted rounded-xl p-6 w-full max-w-lg border border-border max-h-[80vh] overflow-y-auto">
        <h3 className="text-xl font-semibold text-foreground mb-4">Create {object.name}</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          {editableAttributes.map((attr) => (
            <div key={attr.id}>
              <label className="block text-sm font-medium text-foreground mb-1">
                {attr.name}
                {attr.is_required && <span className="text-red-400 ml-1">*</span>}
              </label>
              <FieldEditor
                attribute={attr}
                value={values[attr.slug]}
                onChange={(val) => setValues({ ...values, [attr.slug]: val })}
                required={attr.is_required}
                placeholder={attr.description || `Enter ${attr.name.toLowerCase()}`}
                className="w-full px-4 py-2 bg-accent border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
          ))}
          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-border text-foreground rounded-lg hover:bg-accent transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isCreating}
              className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/50 text-white rounded-lg transition-colors"
            >
              {isCreating ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function RecordsPage() {
  const router = useRouter();
  const params = useParams();
  const objectSlug = params.objectSlug as string;

  const { user, logout } = useAuth();
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.id || null;

  const { objects } = useCRMObjects(workspaceId);
  const currentObject = objects.find((obj) => obj.slug === objectSlug);

  // Saved views
  const {
    views: savedViews,
    createView,
    updateView,
    deleteView,
    isCreating: isCreatingView,
    isUpdating: isUpdatingView,
  } = useSavedViews(workspaceId, currentObject?.id || null);
  const [activeViewId, setActiveViewId] = useState<string | null>(null);

  // View state
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    // Default to board view for deals
    if (objectSlug === "deals") return "board";
    return "table";
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filters, setFilters] = useState<FilterRule[]>([]);
  const [offset, setOffset] = useState(0);
  const [selectedRecords, setSelectedRecords] = useState<string[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createDefaultValues, setCreateDefaultValues] = useState<Record<string, unknown>>({});
  const [sortConfig, setSortConfig] = useState<{ attribute: string; direction: "asc" | "desc" } | null>(null);

  // Debounce free-text search before it reaches the server query.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchQuery), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [searchQuery]);

  // Reset pagination whenever the query-defining state changes, so an old
  // offset never gets applied to a different result set.
  useEffect(() => {
    setOffset(0);
  }, [debouncedSearch, filters, sortConfig, activeViewId]);

  // Column management state
  const [visibleColumns, setVisibleColumns] = useState<string[]>([]);
  const [columnOrder, setColumnOrder] = useState<string[]>([]);
  const [columnDisplayConfig, setColumnDisplayConfig] = useState<ColumnDisplayConfig[]>([]);

  // Initialize columns when object loads
  useEffect(() => {
    if (currentObject?.attributes) {
      const columns = tableAttributes(currentObject.attributes);
      if (visibleColumns.length === 0) {
        setVisibleColumns(columns.slice(0, 5).map((a) => a.slug));
      }
      if (columnOrder.length === 0) {
        setColumnOrder(columns.map((a) => a.slug));
      }
    }
  }, [currentObject?.attributes, visibleColumns.length, columnOrder.length]);

  const handleSaveView = useCallback(async (data: Parameters<typeof createView>[0]) => {
    const view = await createView(data);
    setActiveViewId(view.id);
  }, [createView]);

  const handleUpdateView = useCallback(async (viewId: string, data: Parameters<typeof updateView>[0]["data"]) => {
    await updateView({ viewId, data });
  }, [updateView]);

  const handleDeleteView = useCallback(async (viewId: string) => {
    await deleteView(viewId);
    if (activeViewId === viewId) setActiveViewId(null);
  }, [deleteView, activeViewId]);

  const queryFilters = useMemo(() => toQueryFilters(filters), [filters]);

  const {
    records,
    total,
    isLoading,
    createRecord,
    updateRecord,
    deleteRecord,
    bulkDeleteRecords,
    isCreating,
    isDeleting,
  } = useCRMRecords(workspaceId, currentObject?.id || null, {
    sorts: sortConfig ? [{ attribute: sortConfig.attribute, direction: sortConfig.direction }] : undefined,
    filters: queryFilters.length ? queryFilters : undefined,
    q: debouncedSearch.trim() || undefined,
    limit: PAGE_LIMIT,
    offset,
  });

  // Check if object has status attribute (for board view)
  const hasStatusAttribute = useMemo(() => {
    return currentObject?.attributes?.some((a) => a.attribute_type === "status");
  }, [currentObject]);

  // Synthesize computed columns for person object type
  const synthesizedData = useMemo(() => {
    if (!currentObject || !records.length) {
      return { records: records as CRMRecord[], attributes: (currentObject?.attributes || []) as CRMAttribute[] };
    }
    return applyPersonComputedColumns(
      records as CRMRecord[],
      (currentObject?.attributes || []) as CRMAttribute[],
      currentObject.object_type,
    );
  }, [currentObject, records]);

  const displayAttributes = synthesizedData.attributes;
  const displayRecords = synthesizedData.records;

  // Apply saved view configuration
  const handleSelectView = useCallback((view: TableSavedView | null) => {
    if (!view) {
      setActiveViewId(null);
      // Reset to defaults
      const attrs = displayAttributes.length ? displayAttributes : currentObject?.attributes;
      if (attrs?.length) {
        const columns = tableAttributes(attrs);
        setVisibleColumns(columns.slice(0, 5).map((a) => a.slug));
        setColumnOrder(columns.map((a) => a.slug));
      }
      setSortConfig(null);
      setFilters([]);
      return;
    }
    setActiveViewId(view.id);
    if (view.visible_attributes?.length) {
      setVisibleColumns(view.visible_attributes);
    }
    if (view.sorts?.length) {
      const first = view.sorts[0] as { attribute?: string; direction?: "asc" | "desc" };
      if (first.attribute) {
        setSortConfig({ attribute: first.attribute, direction: first.direction || "asc" });
      }
    } else {
      setSortConfig(null);
    }
    setFilters(fromQueryFilters(view.filters));
    if (view.view_type === "board" || view.view_type === "table") {
      setViewMode(view.view_type as ViewMode);
    }
  }, [currentObject?.attributes, displayAttributes]);

  // Get attributes that should be highlighted on kanban cards
  const kanbanHighlightAttributes = useMemo(() => {
    if (!currentObject?.attributes) return [];
    // Show currency and date fields on cards
    return currentObject.attributes
      .filter((a) => ["currency", "date", "email"].includes(a.attribute_type) && !a.is_system)
      .slice(0, 2)
      .map((a) => a.slug);
  }, [currentObject]);

  const handleSort = (attribute: string) => {
    if (sortConfig?.attribute === attribute) {
      setSortConfig(sortConfig.direction === "asc" ? { attribute, direction: "desc" } : null);
    } else {
      setSortConfig({ attribute, direction: "asc" });
    }
  };

  const handleSelectAll = () => {
    if (selectedRecords.length === records.length) {
      setSelectedRecords([]);
    } else {
      setSelectedRecords(records.map((r) => r.id));
    }
  };

  const handleSelectRecord = (recordId: string) => {
    if (selectedRecords.includes(recordId)) {
      setSelectedRecords(selectedRecords.filter((id) => id !== recordId));
    } else {
      setSelectedRecords([...selectedRecords, recordId]);
    }
  };

  const handleCreate = async (values: Record<string, unknown>) => {
    await createRecord({ values });
    setCreateDefaultValues({});
  };

  const handleDelete = async (recordId: string) => {
    if (confirm("Are you sure you want to delete this record?")) {
      await deleteRecord({ recordId });
    }
  };

  const handleBulkDelete = async () => {
    if (confirm(`Are you sure you want to delete ${selectedRecords.length} records?`)) {
      await bulkDeleteRecords({ recordIds: selectedRecords });
      setSelectedRecords([]);
    }
  };

  const handleRecordClick = (record: CRMRecord) => {
    router.push(`/crm/${objectSlug}/${record.id}`);
  };

  const handleRecordUpdate = async (recordId: string, values: Record<string, unknown>) => {
    await updateRecord({ recordId, data: { values } });
  };

  const handleCreateInStage = (stage: string) => {
    const statusAttr = currentObject?.attributes?.find((a) => a.attribute_type === "status");
    if (statusAttr) {
      setCreateDefaultValues({ [statusAttr.slug]: stage });
    }
    setShowCreateModal(true);
  };

  const handleToggleColumn = (slug: string) => {
    if (visibleColumns.includes(slug)) {
      setVisibleColumns(visibleColumns.filter((s) => s !== slug));
    } else {
      setVisibleColumns([...visibleColumns, slug]);
    }
  };

  if (!currentObject && !isLoading) {
    return (
      <div className="min-h-screen bg-background">
<div className="p-8">
          <div className="max-w-7xl mx-auto">
            <div className="text-center py-16">
              <h2 className="text-2xl font-bold text-foreground mb-2">Object not found</h2>
              <p className="text-muted-foreground mb-4">The object you&apos;re looking for doesn&apos;t exist.</p>
              <button
                onClick={() => router.push("/crm")}
                className="text-purple-400 hover:text-purple-300"
              >
                Go back to CRM
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const icon = currentObject ? objectTypeIcons[currentObject.object_type as CRMObjectType] || objectTypeIcons.custom : null;
  // Board view is always offered: PipelineBoard lets you create a pipeline
  // (and its stage/status attribute) even when the object has none yet.
  const availableViews: ViewMode[] = ["table", "board"];

  return (
    <div className="min-h-screen bg-background">
<div className="p-8">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="flex items-center gap-4 mb-6">
            <button
              onClick={() => router.push("/crm")}
              className="p-2 hover:bg-muted rounded-lg text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            <div className="flex items-center gap-3">
              {icon && <div className="text-purple-400">{icon}</div>}
              <div>
                <h1 className="text-2xl font-bold text-foreground">{currentObject?.plural_name || "Records"}</h1>
                <p className="text-sm text-muted-foreground">{total} records</p>
              </div>
            </div>
            <div className="flex-1" />

            {/* Saved Views */}
            {currentObject && (
              <SavedViewSwitcher
                views={savedViews}
                activeViewId={activeViewId}
                onSelectView={handleSelectView}
                onSaveView={handleSaveView}
                onUpdateView={handleUpdateView}
                onDeleteView={handleDeleteView}
                currentConfig={{
                  visible_attributes: visibleColumns,
                  sorts: sortConfig ? [{ attribute: sortConfig.attribute, direction: sortConfig.direction }] : [],
                  filters: queryFilters,
                  view_type: viewMode as "table" | "board",
                }}
                isCreating={isCreatingView}
                isUpdating={isUpdatingView}
              />
            )}

            {/* View Switcher */}
            <ViewSwitcher
              value={viewMode}
              onChange={setViewMode}
              availableViews={availableViews}
            />

            <button
              onClick={() => {
                setCreateDefaultValues({});
                setShowCreateModal(true);
              }}
              className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
            >
              <Plus className="h-4 w-4" />
              New {currentObject?.name}
            </button>
          </div>

          {/* Toolbar */}
          <div className="flex items-center gap-4 mb-4">
            <SearchInput
              value={searchQuery}
              onChange={setSearchQuery}
              placeholder={`Search ${currentObject?.plural_name?.toLowerCase() || "records"}...`}
              wrapperClassName="flex-1"
            />
            {currentObject?.attributes && (
              <TableFilterPanel
                attributes={currentObject.attributes}
                filters={filters}
                onChange={setFilters}
              />
            )}

            {/* Column visibility (table view only) */}
            {viewMode === "table" && currentObject?.attributes && (
              <ColumnVisibilityMenu
                attributes={tableAttributes(displayAttributes)}
                visibleColumns={visibleColumns}
                onToggleColumn={handleToggleColumn}
                onShowAll={() => setVisibleColumns(tableAttributes(displayAttributes).map((a) => a.slug))}
                onHideAll={() => setVisibleColumns([])}
              />
            )}

            {selectedRecords.length > 0 && (
              <button
                onClick={handleBulkDelete}
                disabled={isDeleting}
                className="flex items-center gap-2 px-4 py-2 bg-red-600/20 hover:bg-red-600/30 border border-red-600/30 text-red-400 rounded-lg transition-colors"
              >
                <Trash2 className="h-4 w-4" />
                Delete ({selectedRecords.length})
              </button>
            )}
          </div>

          {/* Content */}
          {viewMode === "table" ? (
            <DataTable
              records={displayRecords}
              attributes={displayAttributes}
              isLoading={isLoading}
              emptyMessage={searchQuery ? "No records match your search" : `No ${currentObject?.plural_name?.toLowerCase() || "records"} yet`}
              visibleColumns={visibleColumns}
              onVisibleColumnsChange={setVisibleColumns}
              columnOrder={columnOrder}
              onColumnOrderChange={setColumnOrder}
              sortConfig={sortConfig}
              onSort={handleSort}
              selectedRecords={selectedRecords}
              onSelectRecord={handleSelectRecord}
              onSelectAll={handleSelectAll}
              onRecordClick={handleRecordClick}
              onRecordDelete={handleDelete}
              enableColumnReorder={true}
              enableColumnSelector={true}
              columnDisplayConfig={columnDisplayConfig}
              onColumnDisplayConfigChange={setColumnDisplayConfig}
            />
          ) : (
            <>
              {total > PAGE_LIMIT && (
                <div className="mb-3 px-4 py-2 text-sm rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                  Showing {PAGE_LIMIT} of {total} records. Board view does not
                  yet paginate — switch to table view to see the rest.
                </div>
              )}
              {currentObject && workspaceId ? (
                <PipelineBoard
                  workspaceId={workspaceId}
                  object={currentObject}
                  records={records}
                  onRecordClick={handleRecordClick}
                  onRecordUpdate={handleRecordUpdate}
                  onCreateInStage={handleCreateInStage}
                  highlightAttributes={kanbanHighlightAttributes}
                  isLoading={isLoading}
                />
              ) : (
                <KanbanBoard
                  records={records}
                  attributes={currentObject?.attributes || []}
                  onRecordClick={handleRecordClick}
                  onRecordUpdate={handleRecordUpdate}
                  onCreateInStage={handleCreateInStage}
                  highlightAttributes={kanbanHighlightAttributes}
                  isLoading={isLoading}
                />
              )}
            </>
          )}

          {viewMode === "table" && total > PAGE_LIMIT && (
            <div className="flex items-center justify-between mt-4 text-sm text-muted-foreground">
              <span>
                Showing {Math.min(offset + 1, total)}–{Math.min(offset + PAGE_LIMIT, total)} of {total}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_LIMIT))}
                  disabled={offset === 0}
                  className="px-3 py-1.5 border border-border rounded-lg text-foreground hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Previous
                </button>
                <button
                  onClick={() => setOffset(offset + PAGE_LIMIT)}
                  disabled={offset + PAGE_LIMIT >= total}
                  className="px-3 py-1.5 border border-border rounded-lg text-foreground hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Next
                </button>
              </div>
            </div>
          )}

          {currentObject && (
            <CreateRecordModal
              isOpen={showCreateModal}
              onClose={() => {
                setShowCreateModal(false);
                setCreateDefaultValues({});
              }}
              onCreate={handleCreate}
              isCreating={isCreating}
              object={currentObject}
              defaultValues={createDefaultValues}
            />
          )}
        </div>
      </div>
    </div>
  );
}
