"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  crmApi,
  RelationshipsResponse,
  BacklinksResponse,
  CandidateSearchResponse,
  RelationshipGroup,
} from "@/lib/api";

/** Outgoing `record_reference` relationships resolved into authorized
 * summaries, grouped by attribute. Read-only -- no mutation. */
export function useRecordRelationships(
  workspaceId: string | null,
  objectId: string | null,
  recordId: string | null
) {
  const { data, isLoading, error, refetch } = useQuery<RelationshipsResponse>({
    queryKey: ["crmRecordRelationships", workspaceId, objectId, recordId],
    queryFn: () => crmApi.relationships.get(workspaceId!, objectId!, recordId!),
    enabled: !!workspaceId && !!objectId && !!recordId,
  });

  return {
    groups: data?.groups || [],
    isLoading,
    error,
    refetch,
  };
}

/** Incoming backlinks: authorized records elsewhere in the workspace that
 * reference this record. Never persisted -- derived fresh on every call. */
export function useRecordBacklinks(
  workspaceId: string | null,
  objectId: string | null,
  recordId: string | null,
  params?: { limit?: number; offset?: number; include_archived?: boolean }
) {
  const { data, isLoading, error, refetch } = useQuery<BacklinksResponse>({
    queryKey: ["crmRecordBacklinks", workspaceId, objectId, recordId, params],
    queryFn: () => crmApi.relationships.backlinks(workspaceId!, objectId!, recordId!, params),
    enabled: !!workspaceId && !!objectId && !!recordId,
  });

  return {
    items: data?.items || [],
    total: data?.total || 0,
    limit: data?.limit ?? params?.limit ?? 50,
    offset: data?.offset ?? params?.offset ?? 0,
    isLoading,
    error,
    refetch,
  };
}

/** Read-only candidate search for a future relationship picker. Debounce
 * the `q` value before passing it in -- this hook does not debounce
 * itself, so callers control that (see RelationshipCandidatePicker). */
export function useRelationshipCandidates(
  workspaceId: string | null,
  objectId: string | null,
  params: {
    target_object_id: string | null;
    q?: string;
    limit?: number;
    offset?: number;
    exclude_record_id?: string;
    exclude_ids?: string[];
    include_archived?: boolean;
  },
  enabled: boolean = true
) {
  const { data, isLoading, error } = useQuery<CandidateSearchResponse>({
    queryKey: ["crmRelationshipCandidates", workspaceId, objectId, params],
    queryFn: () =>
      crmApi.relationships.searchCandidates(workspaceId!, objectId!, {
        ...params,
        target_object_id: params.target_object_id!,
      }),
    enabled: enabled && !!workspaceId && !!objectId && !!params.target_object_id,
  });

  return {
    items: data?.items || [],
    total: data?.total || 0,
    limit: data?.limit ?? params.limit ?? 50,
    offset: data?.offset ?? params.offset ?? 0,
    isLoading,
    error,
  };
}

/** Set a `record_reference` attribute to its desired final value (full
 * replace). No optimistic update -- the relationships query is invalidated
 * and refetched only after the server confirms success, so a failed
 * mutation never shows as though it succeeded. */
export function useMutateRelationship(
  workspaceId: string | null,
  objectId: string | null,
  recordId: string | null
) {
  const queryClient = useQueryClient();

  const mutation = useMutation<
    RelationshipGroup,
    unknown,
    { attributeId: string; value: string | string[] | null }
  >({
    mutationFn: ({ attributeId, value }) =>
      crmApi.relationships.mutate(workspaceId!, objectId!, recordId!, attributeId, value),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["crmRecordRelationships", workspaceId, objectId, recordId],
      });
    },
  });

  return {
    mutate: mutation.mutate,
    mutateAsync: mutation.mutateAsync,
    isPending: mutation.isPending,
    error: mutation.error,
    reset: mutation.reset,
    variables: mutation.variables,
  };
}
