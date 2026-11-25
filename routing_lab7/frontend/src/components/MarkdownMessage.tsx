import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import type { Components } from "react-markdown";

// Minimal Tailwind-styled overrides instead of pulling in the full
// @tailwindcss/typography plugin, per
// instructions/learnings/chat-ui-plan1.md section 2.6's "prefer the
// lightest option" guidance - this project's answers are plain prose
// with occasional lists/emphasis/code, not rich documents.
const components: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  code: ({ children }) => <code className="rounded bg-slate-200 px-1 text-[0.85em] dark:bg-slate-700">{children}</code>,
  a: ({ children, href }) => (
    <a href={href} className="underline" target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
};

/**
 * Renders an assistant answer's Markdown (the synthesis agent's prose
 * commonly includes lists/emphasis) through `rehype-sanitize` - defense
 * in depth against a prompt-injected or misbehaving LLM response
 * containing raw HTML, even though this project's answers come from a
 * controlled pipeline rather than untrusted user-supplied HTML. See
 * instructions/learnings/chat-ui-plan1.md section 2.1/2.3.
 */
export function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown rehypePlugins={[rehypeSanitize]} components={components}>
      {content}
    </ReactMarkdown>
  );
}
