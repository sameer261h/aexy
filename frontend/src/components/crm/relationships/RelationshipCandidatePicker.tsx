"use client";

import { useEffect, useState } from "react";
import { Search, Archive } from "lucide-react";
import { CandidateRecord } from "@/lib/api";
import { useRelationshipCandidates } from "@/hooks/useCRMRelationships";

const SEARCH_DEBOUNCE_MS = 300;

interface RelationshipCandidatePickerProps {
  workspaceId: string | null;
  /** Object context the search is performed from (authorization scope). */
  objectId: string | null;
  /** Object being searched for candidates. */
  targetObjectId: string | null;
  excludeRecordId?: string;
  excludeIds?: string[];
  placeholder?: string;
  /** Fires with the chosen candidate. This component never persists the
   * selection itself -- it is purely a search-and-callback picker, not an
   * editor. Whether the selection is actually saved is entirely up to the
   * caller (e.g. `RelationshipsPanel` calls the mutation endpoint from its
   * own `onSelect`; a read-only caller can pass a no-op). */
  onSelect: (candidate: CandidateRecord) => void;
}

/** Reusable, debounced candidate search. Never calls a save API itself and
 * never remembers the selection -- it only invokes `onSelect` with the
 * chosen candidate and clears the search, exactly like a "jump to" search
 * rather than an editor. Callers that do persist the selection should show
 * their own saving/error state; this component makes no claim either way. */
export function RelationshipCandidatePicker({
  workspaceId,
  objectId,
  targetObjectId,
  excludeRecordId,
  excludeIds,
  placeholder = "Search records…",
  onSelect,
}: RelationshipCandidatePickerProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [lastSelected, setLastSelected] = useState<CandidateRecord | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!lastSelected) return;
    const t = setTimeout(() => setLastSelected(null), 2500);
    return () => clearTimeout(t);
  }, [lastSelected]);

  const { items, total, isLoading, error } = useRelationshipCandidates(
    workspaceId,
    objectId,
    {
      target_object_id: targetObjectId,
      q: debouncedQuery.trim() || undefined,
      limit: 20,
      exclude_record_id: excludeRecordId,
      exclude_ids: excludeIds,
    },
    query.length > 0
  );

  const handleSelect = (candidate: CandidateRecord) => {
    onSelect(candidate);
    setLastSelected(candidate);
    setQuery("");
    setDebouncedQuery("");
  };

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          disabled={!targetObjectId}
          className="w-full pl-9 pr-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-purple-500/50 disabled:opacity-50"
        />
      </div>

      {lastSelected && (
        <p className="text-xs text-purple-400">
          Selected &quot;{lastSelected.record_label}&quot;.
        </p>
      )}

      {query.length > 0 && (
        <div className="border border-border rounded-lg bg-muted/30 max-h-64 overflow-y-auto">
          {isLoading && (
            <div className="px-3 py-3 text-sm text-muted-foreground">Searching…</div>
          )}
          {error && (
            <div className="px-3 py-3 text-sm text-red-400">Search failed.</div>
          )}
          {!isLoading && !error && items.length === 0 && (
            <div className="px-3 py-3 text-sm text-muted-foreground">No matching records</div>
          )}
          {!isLoading && !error && items.length > 0 && (
            <ul>
              {items.map((candidate) => (
                <li key={candidate.record_id}>
                  <button
                    type="button"
                    onClick={() => handleSelect(candidate)}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-accent transition-colors"
                  >
                    <span className="truncate">{candidate.record_label}</span>
                    {candidate.is_archived && <Archive className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!isLoading && !error && total > items.length && (
            <div className="px-3 py-1.5 text-xs text-muted-foreground border-t border-border">
              Showing {items.length} of {total} matches -- refine your search to narrow down.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
