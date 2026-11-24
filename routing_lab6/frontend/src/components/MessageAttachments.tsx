import { useEffect, useState } from "react";

import { fetchAttachmentBlob } from "../api/client";
import type { AttachmentMeta } from "../api/client";

/** An image attachment's thumbnail, fetched with the auth header (a
 * plain <img src> can't send one) and shown via an object URL. Falls
 * back to a filename pill while loading or on failure. */
function AttachmentImage({ threadId, meta }: { threadId: string; meta: AttachmentMeta }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    fetchAttachmentBlob(threadId, meta.attachment_id)
      .then((blob) => {
        if (cancelled) return;
        revoked = URL.createObjectURL(blob);
        setObjectUrl(revoked);
      })
      .catch(() => {
        // Pill fallback below - a missing thumbnail isn't an error state.
      });
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [threadId, meta.attachment_id]);

  if (!objectUrl) {
    return (
      <span className="rounded-lg border border-slate-300 px-2 py-1 text-xs text-slate-600 dark:border-slate-600 dark:text-slate-300">
        🖼 {meta.filename}
      </span>
    );
  }
  return (
    <img
      src={objectUrl}
      alt={`Attachment: ${meta.filename}`}
      title={meta.filename}
      className="max-h-32 rounded-lg border border-slate-200 object-cover dark:border-slate-700"
    />
  );
}

/** The attachments attached to a (user) message - image thumbnails or
 * filename pills (chat-ui-plan4.md §2.2). */
export function MessageAttachments({
  threadId,
  attachments,
}: {
  threadId: string;
  attachments: AttachmentMeta[];
}) {
  return (
    <div className="mb-1 flex max-w-[85%] flex-wrap justify-end gap-1.5 sm:max-w-[75%]">
      {attachments.map((meta) =>
        meta.media_type.startsWith("image/") ? (
          <AttachmentImage key={meta.attachment_id} threadId={threadId} meta={meta} />
        ) : (
          <span
            key={meta.attachment_id}
            className="rounded-lg border border-slate-300 px-2 py-1 text-xs text-slate-600 dark:border-slate-600 dark:text-slate-300"
          >
            📄 {meta.filename}
          </span>
        ),
      )}
    </div>
  );
}
