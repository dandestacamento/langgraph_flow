import { Suspense, lazy, useState } from "react";

import { ChatWindow } from "./components/ChatWindow";
import { Composer } from "./components/Composer";
import keycloak from "./auth/keycloak";
import { useChat } from "./hooks/useChat";

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
    newConversation,
    switchConversation,
  } = useChat();
  const username = keycloak.tokenParsed?.preferred_username as string | undefined;
  // Mobile-only: the sidebar is a toggleable overlay below md, a fixed
  // column at md and up (where `sidebarOpen` is simply irrelevant).
  const [sidebarOpen, setSidebarOpen] = useState(false);

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
      />
    </Suspense>
  );

  return (
    <div className="flex h-dvh bg-white">
      <aside className="hidden w-64 shrink-0 md:block">{sidebar(false)}</aside>
      {sidebarOpen && (
        <div className="fixed inset-0 z-20 flex md:hidden">
          <div className="w-72 max-w-[80vw] bg-slate-50 shadow-xl">{sidebar(true)}</div>
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
          <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <div className="flex items-center gap-2">
              <button
                type="button"
                aria-label="Open conversation list"
                onClick={() => setSidebarOpen(true)}
                className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50 md:hidden"
              >
                ☰
              </button>
              <div>
                <h1 className="text-base font-semibold text-slate-900">
                  Appliance Troubleshooting Chat
                </h1>
                <p className="text-xs text-slate-500">routing_lab3 - custom FastAPI backend</p>
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              {username && <span>{username}</span>}
              <button
                type="button"
                onClick={() => keycloak.logout()}
                className="rounded border border-slate-300 px-2 py-1 font-medium hover:bg-slate-50"
              >
                Log out
              </button>
            </div>
          </header>
          <ChatWindow messages={messages} isLoadingHistory={isLoadingHistory} />
          {error && (
            <div className="flex items-center justify-between gap-2 px-4 pb-2 text-xs text-red-600">
              <span>{error}</span>
              <button
                type="button"
                onClick={retryLastMessage}
                className="shrink-0 rounded border border-red-300 px-2 py-0.5 font-medium hover:bg-red-50"
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
