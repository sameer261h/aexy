"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSendRecordEmail } from "@/hooks/useCRM";

interface RecordEmailComposerProps {
  isOpen: boolean;
  onClose: () => void;
  workspaceId: string;
  objectId: string;
  recordId: string;
  recipientEmail: string;
}

export function RecordEmailComposer({
  isOpen,
  onClose,
  workspaceId,
  objectId,
  recordId,
  recipientEmail,
}: RecordEmailComposerProps) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const { sendEmail, isSending } = useSendRecordEmail(
    workspaceId,
    objectId,
    recordId,
  );

  const handleSend = async () => {
    // Plain text in, sent as the HTML body -- no rich-text editor for a
    // first version, matching how record notes are composed elsewhere.
    await sendEmail({ subject, body_html: body.replace(/\n/g, "<br/>") });
    setSubject("");
    setBody("");
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Send email to {recipientEmail}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <Input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Subject"
            maxLength={500}
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Write your message..."
            rows={8}
            className="w-full px-4 py-3 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSending}>
            Cancel
          </Button>
          <Button
            onClick={handleSend}
            disabled={isSending || !subject.trim() || !body.trim()}
          >
            {isSending ? "Sending..." : "Send"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
