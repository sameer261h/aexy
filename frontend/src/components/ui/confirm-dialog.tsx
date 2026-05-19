"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export type ConfirmTone = "danger" | "warning" | "neutral";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Primary action label. Defaults to common.confirm. */
  confirmLabel?: React.ReactNode;
  /** Cancel label. Defaults to common.cancel. */
  cancelLabel?: React.ReactNode;
  /** Visual treatment for the primary action. */
  tone?: ConfirmTone;
  /** Async confirm handler. Dialog stays open while the promise resolves. */
  onConfirm: () => void | Promise<void>;
  /** Disable the primary button externally (e.g. while parent mutation is pending). */
  isPending?: boolean;
}

const toneStyles: Record<ConfirmTone, { btn: string; iconBg: string; iconFg: string }> = {
  danger: {
    btn: "bg-red-600 hover:bg-red-700 text-white",
    iconBg: "bg-red-500/15",
    iconFg: "text-red-400",
  },
  warning: {
    btn: "bg-amber-600 hover:bg-amber-700 text-white",
    iconBg: "bg-amber-500/15",
    iconFg: "text-amber-400",
  },
  neutral: {
    btn: "bg-indigo-600 hover:bg-indigo-700 text-white",
    iconBg: "bg-indigo-500/15",
    iconFg: "text-indigo-400",
  },
};

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel,
  tone = "danger",
  onConfirm,
  isPending,
}: ConfirmDialogProps) {
  const tc = useTranslations("common");
  const [localPending, setLocalPending] = React.useState(false);
  const pending = isPending || localPending;
  const styles = toneStyles[tone];

  const handleConfirm = async () => {
    try {
      setLocalPending(true);
      await onConfirm();
      onOpenChange(false);
    } finally {
      setLocalPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={pending ? undefined : onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-start gap-3">
            <div className={cn("rounded-full p-2 shrink-0", styles.iconBg)}>
              <AlertTriangle className={cn("h-5 w-5", styles.iconFg)} />
            </div>
            <div className="flex-1 min-w-0">
              <DialogTitle>{title}</DialogTitle>
              {description ? (
                <DialogDescription className="mt-1.5">{description}</DialogDescription>
              ) : null}
            </div>
          </div>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={pending}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-border text-foreground hover:bg-accent disabled:opacity-50 transition"
          >
            {cancelLabel ?? tc("cancel")}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={pending}
            className={cn(
              "px-4 py-2 text-sm font-medium rounded-lg inline-flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed transition",
              styles.btn,
            )}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {confirmLabel ?? tc("confirm")}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
