"use client";

import { useState } from "react";
import { CRMLeadConvertResult } from "@/lib/api";
import { useConvertLead } from "@/hooks/usePipelines";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface ConvertLeadDialogProps {
  isOpen: boolean;
  onClose: () => void;
  workspaceId: string;
  recordId: string;
  onConverted?: (result: CRMLeadConvertResult) => void;
}

export function ConvertLeadDialog({
  isOpen,
  onClose,
  workspaceId,
  recordId,
  onConverted,
}: ConvertLeadDialogProps) {
  const convert = useConvertLead(workspaceId);
  const [createCompany, setCreateCompany] = useState(true);
  const [createContact, setCreateContact] = useState(true);
  const [createDeal, setCreateDeal] = useState(true);
  const [archive, setArchive] = useState(false);

  const handleConvert = () => {
    convert.mutate(
      {
        recordId,
        data: {
          create_company: createCompany,
          create_contact: createContact,
          create_deal: createDeal,
          archive_after_convert: archive,
        },
      },
      {
        onSuccess: (result) => {
          onConverted?.(result);
          onClose();
        },
      }
    );
  };

  const Row = ({
    checked,
    onChange,
    label,
    hint,
  }: {
    checked: boolean;
    onChange: (v: boolean) => void;
    label: string;
    hint: string;
  }) => (
    <label className="flex items-start gap-3 rounded-lg border border-border/40 p-3 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1"
      />
      <span>
        <span className="block text-sm font-medium">{label}</span>
        <span className="block text-xs text-muted-foreground">{hint}</span>
      </span>
    </label>
  );

  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Convert lead</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <Row
            checked={createCompany}
            onChange={setCreateCompany}
            label="Create Company"
            hint="From the lead's company name"
          />
          <Row
            checked={createContact}
            onChange={setCreateContact}
            label="Create Contact"
            hint="A Person record linked to the company"
          />
          <Row
            checked={createDeal}
            onChange={setCreateDeal}
            label="Create Deal"
            hint="Placed in the first stage of the default sales pipeline"
          />
          <label className="flex items-center gap-3 px-1 pt-1 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={archive}
              onChange={(e) => setArchive(e.target.checked)}
            />
            Archive the lead after converting
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleConvert} disabled={convert.isPending}>
            {convert.isPending ? "Converting…" : "Convert"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
