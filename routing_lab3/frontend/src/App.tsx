import { Suspense, lazy, useEffect, useState } from "react";

import { ChatWindow } from "./components/ChatWindow";
import { Composer } from "./components/Composer";
import keycloak from "./auth/keycloak";
import { useChat } from "./hooks/useChat";
import { useTheme } from "./hooks/useTheme";

// Code-split: the sidebar isn't needed for first paint of the chat
// itself (chat-ui-plan1.md section 2.6 named it as the lazy candidate).
const ConversationSidebar = lazy(() => import("./components/ConversationSidebar"));

function App() {
  const {
    threadId,
    threads,
    messages,
    isSending,
    isLoadingHistory,
    error,
    sendMessage,
    retryLastMessage,
    regenerateLastTurn,
    newConversation,
    switchConversation,
    renameConversation,
    deleteConversation,
  } = useChat();
  const { theme, toggleTheme } = useTheme();
  const username = keycloak.tokenParsed?.preferred_username as string | undefined;
  // Mobile-only: the sidebar is a toggleable overlay below md, a fixed
  // column at md and up (where `sidebarOpen` is simply irrelevant).
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // The active conversation's title - undefined until its first message
  // has been sent (that's when the backend creates/titles it). Shown in
  // the header and the browser tab so it's always clear *which*
  // conversation is open, not just via the sidebar highlight (a real
  // point of confusion observed in testing, chat-ui-plan2.md).
  const activeTitle = threads.find((t) => t.thread_id === threadId)?.title;

  useEffect(() => {
    document.title = activeTitle
      ? `${activeTitle} - Appliance Troubleshooting Chat`
      : "Appliance Troubleshooting Chat";
  }, [activeTitle]);

  const sidebar = (closeAfterAction: boolean) => (
    <Suspense fallback={null}>
      <ConversationSidebar
        threads={threads}
        activeThreadId={threadId}
        disabled={isSending}
        onSelect={(id) => {
          switchConversation(id);
          if (closeAfterAction) setSidebarOpen(false);
        }}
        onNew={() => {
          newConversation();
          if (closeAfterAction) setSidebarOpen(false);
        }}
        onRename={(id, title) => void renameConversation(id, title)}
        onDelete={(id) => void deleteConversation(id)}
      />
    </Suspense>
  );

  return (
    <div className="flex h-dvh bg-white dark:bg-slate-950">
      <aside className="hidden w-64 shrink-0 md:block">{sidebar(false)}</aside>
      {sidebarOpen && (
        <div className="fixed inset-0 z-20 flex md:hidden">
          <div className="w-72 max-w-[80vw] bg-slate-50 shadow-xl dark:bg-slate-900">{sidebar(true)}</div>
          <button
            type="button"
            aria-label="Close conversation list"
            onClick={() => setSidebarOpen(false)}
            className="flex-1 bg-slate-900/40"
          />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mx-auto flex h-full w-full max-w-2xl flex-col">
          <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700">
            <div className="flex items-center gap-2">
              <button
                type="button"
                aria-label="Open conversation list"
                onClick={() => setSidebarOpen(true)}
                className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-800 md:hidden"
              >
                ☰
              </button>
              <div className="min-w-0">
                <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  Appliance Troubleshooting Chat
                </h1>
                <p
                  className="truncate text-xs text-slate-500 dark:text-slate-400"
                  title={activeTitle ?? "New conversation"}
                >
                  {activeTitle ?? "New conversation"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              {username && <span>{username}</span>}
              <button
                type="button"
                onClick={toggleTheme}
                aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                className="rounded border border-slate-300 px-2 py-1 font-medium hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800"
              >
                {theme === "dark" ? "☀" : "☾"}
              </button>
              <button
                type="button"
                onClick={() => keycloak.logout()}
                className="rounded border border-slate-300 px-2 py-1 font-medium hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800"
              >
                Log out
              </button>
            </div>
          </header>
          <ChatWindow
            messages={messages}
            isLoadingHistory={isLoadingHistory}
            onRegenerate={isSending ? undefined : regenerateLastTurn}
          />
          {error && (
            <div className="flex items-center justify-between gap-2 px-4 pb-2 text-xs text-red-600 dark:text-red-400">
              <span>{error}</span>
              <button
                type="button"
                onClick={retryLastMessage}
                className="shrink-0 rounded border border-red-300 px-2 py-0.5 font-medium hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
              >
                Retry
              </button>
            </div>
          )}
          <Composer onSend={(text) => sendMessage(text)} disabled={isSending} />
        </div>
      </div>
    </div>
  );
}

export default App;
