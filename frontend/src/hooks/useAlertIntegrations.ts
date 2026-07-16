"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  alertIntegrationsApi,
  AlertIntegration,
  AlertIntegrationCreate,
  AlertIntegrationUpdate,
  AlertIntegrationWithSecret,
} from "@/lib/api";

const key = (workspaceId: string | null) => ["alertIntegrations", workspaceId];

export function useAlertIntegrations(workspaceId: string | null) {
  return useQuery<AlertIntegration[]>({
    queryKey: key(workspaceId),
    queryFn: () => alertIntegrationsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });
}

export function useAlertIntegrationEvents(
  workspaceId: string | null,
  integrationId: string | null,
  limit = 50
) {
  return useQuery({
    queryKey: ["alertIntegrationEvents", workspaceId, integrationId, limit],
    queryFn: () => alertIntegrationsApi.listEvents(workspaceId!, integrationId!, { limit }),
    enabled: !!workspaceId && !!integrationId,
  });
}

export function useAlertIntegrationMutations(workspaceId: string | null) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: key(workspaceId) });

  const create = useMutation<AlertIntegrationWithSecret, unknown, AlertIntegrationCreate>({
    mutationFn: (data) => alertIntegrationsApi.create(workspaceId!, data),
    onSuccess: () => {
      invalidate();
      toast.success("Alert integration created");
    },
    onError: () => toast.error("Failed to create integration"),
  });

  const update = useMutation<AlertIntegration, unknown, { id: string; data: AlertIntegrationUpdate }>({
    mutationFn: ({ id, data }) => alertIntegrationsApi.update(workspaceId!, id, data),
    onSuccess: () => {
      invalidate();
      toast.success("Integration updated");
    },
    onError: () => toast.error("Failed to update integration"),
  });

  const rotateSecret = useMutation<AlertIntegrationWithSecret, unknown, string>({
    mutationFn: (id) => alertIntegrationsApi.rotateSecret(workspaceId!, id),
    onSuccess: () => {
      invalidate();
      toast.success("Signing secret rotated");
    },
    onError: () => toast.error("Failed to rotate secret"),
  });

  const remove = useMutation<void, unknown, string>({
    mutationFn: (id) => alertIntegrationsApi.remove(workspaceId!, id),
    onSuccess: () => {
      invalidate();
      toast.success("Integration deleted");
    },
    onError: () => toast.error("Failed to delete integration"),
  });

  return { create, update, rotateSecret, remove };
}
