import { useState } from "react";

/** Small icon-free text button that copies `text` to the clipboard and
 * shows a brief "Copied" confirmation - kept as its own component since
 * both the message list and (later) other surfaces may want it. */
export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleClick() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="text-xs text-slate-400 hover:text-slate-600"
      aria-label="Copy message"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
