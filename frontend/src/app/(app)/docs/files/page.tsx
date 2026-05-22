import { redirect } from "next/navigation";

// Bare /docs/files has no valid sourceType/sourceId, so the [documentId]
// catch-all used to swallow it and load forever waiting for a doc named
// "files". Redirect to the workspace drive view, which is where the
// sidebar "Files" entries actually live.
export default function DocsFilesIndex() {
  redirect("/docs/drive");
}
