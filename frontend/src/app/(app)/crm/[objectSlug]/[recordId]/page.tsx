"use client";

import { useState, useMemo } from "react";
import { useRouter, useParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import {
  useCRMObjects,
  useCRMRecord,
  useCRMRecords,
  useCRMNotes,
  useCRMActivities,
} from "@/hooks/useCRM";
import { RecordHeader } from "@/components/crm/RecordHeader";
import { RecordHighlights } from "@/components/crm/RecordHighlights";
import { RecordSidebar } from "@/components/crm/RecordSidebar";
import { ConvertLeadDialog } from "@/components/crm/ConvertLeadDialog";
import { Button } from "@/components/ui/button";
import {
  RecordTabs,
  RecordTabId,
  NotesTabContent,
  ActivityTabContent,
  OverviewTabContent,
} from "@/components/crm/RecordTabs";
import { RelationshipsPanel } from "@/components/crm/relationships/RelationshipsPanel";
import { BacklinksPanel } from "@/components/crm/relationships/BacklinksPanel";
import { RelationshipCandidatePicker } from "@/components/crm/relationships/RelationshipCandidatePicker";
import { useRecordRelationships, useRecordBacklinks } from "@/hooks/useCRMRelationships";

export default function RecordDetailPage() {
  const router = useRouter();
  const params = useParams();
  const objectSlug = params.objectSlug as string;
  const recordId = params.recordId as string;

  const { user, logout } = useAuth();
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.id || null;
  const [showConvert, setShowConvert] = useState(false);

  // Fetch data
  const { objects } = useCRMObjects(workspaceId);
  const currentObject = objects.find((obj) => obj.slug === objectSlug);

  const {
    record,
    isLoading: isLoadingRecord,
    updateRecord,
    deleteRecord,
    isUpdating,
    isDeleting,
    refetch: refetchRecord,
  } = useCRMRecord(workspaceId, recordId);

  // Fetch all records for prev/next navigation
  const { records: allRecords } = useCRMRecords(workspaceId, currentObject?.id || null);

  const {
    notes,
    isLoading: isLoadingNotes,
    createNote,
    updateNote,
    deleteNote,
    isCreating: isCreatingNote,
  } = useCRMNotes(workspaceId, recordId);

  const { activities, isLoading: isLoadingActivities } = useCRMActivities(
    workspaceId,
    recordId
  );

  // Relationship counts for the "Related" tab badge -- same queries the
  // panels below run, so react-query dedupes them rather than double-fetching.
  const { groups: relationshipGroups } = useRecordRelationships(
    workspaceId, currentObject?.id || null, recordId
  );
  const { total: backlinksTotal } = useRecordBacklinks(
    workspaceId, currentObject?.id || null, recordId
  );
  const relatedCount =
    relationshipGroups.reduce((sum, g) => sum + g.total, 0) + backlinksTotal;

  // UI State
  const [isEditing, setIsEditing] = useState(false);
  const [editedValues, setEditedValues] = useState<Record<string, unknown>>({});
  const [activeTab, setActiveTab] = useState<RecordTabId>("overview");
  const [newNote, setNewNote] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [candidateTargetObjectId, setCandidateTargetObjectId] = useState<string | null>(null);

  // Navigation helpers
  const currentIndex = useMemo(() => {
    if (!record || !allRecords.length) return -1;
    return allRecords.findIndex((r) => r.id === record.id);
  }, [record, allRecords]);

  const hasPrev = currentIndex > 0;
  const hasNext = currentIndex >= 0 && currentIndex < allRecords.length - 1;

  const navigateToPrev = () => {
    if (hasPrev) {
      const prevRecord = allRecords[currentIndex - 1];
      router.push(`/crm/${objectSlug}/${prevRecord.id}`);
    }
  };

  const navigateToNext = () => {
    if (hasNext) {
      const nextRecord = allRecords[currentIndex + 1];
      router.push(`/crm/${objectSlug}/${nextRecord.id}`);
    }
  };

  // Edit handlers
  const handleSave = async () => {
    await updateRecord({ values: editedValues });
    setIsEditing(false);
    setEditedValues({});
  };

  const handleCancel = () => {
    setIsEditing(false);
    setEditedValues({});
  };

  const handleDelete = async () => {
    if (confirm("Are you sure you want to delete this record?")) {
      await deleteRecord(false);
      router.push(`/crm/${objectSlug}`);
    }
  };

  const startEditing = () => {
    setEditedValues(record?.values || {});
    setIsEditing(true);
  };

  // Note handlers
  const handleCreateNote = async () => {
    if (!newNote.trim()) return;
    await createNote({ content: newNote });
    setNewNote("");
  };

  const handleDeleteNote = async (noteId: string) => {
    if (confirm("Delete this note?")) {
      await deleteNote(noteId);
    }
  };

  const handleTogglePin = async (noteId: string, isPinned: boolean) => {
    await updateNote({ noteId, data: { is_pinned: !isPinned } });
  };

  const handleValueChange = (slug: string, value: unknown) => {
    setEditedValues((prev) => ({ ...prev, [slug]: value }));
  };

  // Loading state
  if (isLoadingRecord || !record) {
    return (
      <div className="min-h-screen bg-background">
<div className="p-8">
          <div className="max-w-7xl mx-auto">
            <div className="animate-pulse space-y-6">
              <div className="flex items-center gap-4">
                <div className="h-10 w-10 bg-muted rounded" />
                <div className="h-12 w-12 bg-muted rounded-xl" />
                <div className="flex-1">
                  <div className="h-6 w-48 bg-muted rounded mb-2" />
                  <div className="h-4 w-24 bg-muted rounded" />
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="h-20 bg-muted rounded-xl" />
                <div className="h-20 bg-muted rounded-xl" />
                <div className="h-20 bg-muted rounded-xl" />
              </div>
              <div className="h-64 bg-muted rounded-xl" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  const attributes = currentObject?.attributes || [];
  const pinnedNotes = notes.filter((n) => n.is_pinned);

  return (
    <div className="min-h-screen bg-background">
<div className="flex">
        {/* Main content area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="px-8 pt-6 pb-4 border-b border-border">
            <RecordHeader
              record={record}
              object={currentObject}
              onBack={() => router.push(`/crm/${objectSlug}`)}
              onPrev={navigateToPrev}
              onNext={navigateToNext}
              hasPrev={hasPrev}
              hasNext={hasNext}
              isEditing={isEditing}
              isUpdating={isUpdating}
              isDeleting={isDeleting}
              onEdit={startEditing}
              onSave={handleSave}
              onCancel={handleCancel}
              onDelete={handleDelete}
            />
          </div>

          {/* Lead conversion */}
          {currentObject?.object_type === "lead" &&
            record.values?.lead_status !== "converted" &&
            workspaceId && (
              <div className="px-8 pt-4">
                <div className="flex items-center justify-between rounded-lg border border-purple-500/30 bg-purple-500/5 px-4 py-3">
                  <span className="text-sm text-muted-foreground">
                    Ready to move this lead forward?
                  </span>
                  <Button size="sm" onClick={() => setShowConvert(true)}>
                    Convert lead
                  </Button>
                </div>
              </div>
            )}

          {/* Highlights */}
          <div className="px-8 py-6">
            <RecordHighlights
              record={record}
              attributes={attributes}
              maxCards={6}
            />
          </div>

          {/* Tabs */}
          <div className="px-8">
            <RecordTabs
              activeTab={activeTab}
              onTabChange={setActiveTab}
              notesCount={notes.length}
              activitiesCount={activities.length}
              relatedCount={relatedCount}
            />
          </div>

          {/* Tab content */}
          <div className="flex-1 px-8 py-6 overflow-y-auto">
            {activeTab === "overview" && (
              <OverviewTabContent
                record={record}
                attributes={attributes}
                recentActivities={activities}
                pinnedNotes={pinnedNotes}
                onNoteTogglePin={handleTogglePin}
                onNoteDelete={handleDeleteNote}
                onViewAllActivity={() => setActiveTab("activity")}
                onViewAllNotes={() => setActiveTab("notes")}
              />
            )}

            {activeTab === "notes" && (
              <NotesTabContent
                notes={notes}
                isLoading={isLoadingNotes}
                newNote={newNote}
                onNewNoteChange={setNewNote}
                onCreateNote={handleCreateNote}
                onDeleteNote={handleDeleteNote}
                onTogglePin={handleTogglePin}
                isCreating={isCreatingNote}
              />
            )}

            {activeTab === "activity" && (
              <ActivityTabContent
                activities={activities}
                isLoading={isLoadingActivities}
              />
            )}

            {activeTab === "related" && (
              <div className="space-y-8">
                <div>
                  <h3 className="text-sm font-semibold text-foreground mb-3">Relationships</h3>
                  <RelationshipsPanel
                    workspaceId={workspaceId}
                    objectId={currentObject?.id || null}
                    recordId={recordId}
                    objects={objects}
                  />
                </div>

                <div>
                  <h3 className="text-sm font-semibold text-foreground mb-3">Referenced by</h3>
                  <BacklinksPanel
                    workspaceId={workspaceId}
                    objectId={currentObject?.id || null}
                    recordId={recordId}
                    objects={objects}
                  />
                </div>

                <div>
                  <h3 className="text-sm font-semibold text-foreground mb-3">Find records</h3>
                  <div className="flex items-center gap-2 mb-2">
                    <label className="text-xs text-muted-foreground">In:</label>
                    <select
                      value={candidateTargetObjectId || currentObject?.id || ""}
                      onChange={(e) => setCandidateTargetObjectId(e.target.value)}
                      className="text-xs bg-muted border border-border rounded-md px-2 py-1 text-foreground"
                    >
                      {objects.map((o) => (
                        <option key={o.id} value={o.id}>{o.plural_name}</option>
                      ))}
                    </select>
                  </div>
                  <RelationshipCandidatePicker
                    workspaceId={workspaceId}
                    objectId={currentObject?.id || null}
                    targetObjectId={candidateTargetObjectId || currentObject?.id || null}
                    excludeRecordId={recordId}
                    onSelect={() => {
                      // Read-only demonstration: the picker only reports a
                      // selection via this callback. Nothing is persisted --
                      // there is no relationship-write endpoint yet.
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <RecordSidebar
          record={record}
          attributes={attributes}
          isEditing={isEditing}
          editedValues={editedValues}
          onValueChange={handleValueChange}
          isCollapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          notes={notes}
          onTogglePin={handleTogglePin}
          onDeleteNote={handleDeleteNote}
        />
      </div>

      {workspaceId && (
        <ConvertLeadDialog
          isOpen={showConvert}
          onClose={() => setShowConvert(false)}
          workspaceId={workspaceId}
          recordId={recordId}
          onConverted={() => refetchRecord?.()}
        />
      )}
    </div>
  );
}
