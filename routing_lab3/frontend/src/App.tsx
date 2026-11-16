import { ChatWindow } from "./components/ChatWindow";
import { Composer } from "./components/Composer";
import { useChat } from "./hooks/useChat";

function App() {
  const { messages, isSending, error, sendMessage } = useChat();

  return (
    <div className="mx-auto flex h-screen max-w-2xl flex-col bg-white">
      <header className="border-b border-slate-200 px-4 py-3">
        <h1 className="text-base font-semibold text-slate-900">Appliance Troubleshooting Chat</h1>
        <p className="text-xs text-slate-500">routing_lab3 - custom FastAPI backend</p>
      </header>
      <ChatWindow messages={messages} />
      {error && <p className="px-4 pb-2 text-xs text-red-600">{error}</p>}
      <Composer onSend={(text) => sendMessage(text)} disabled={isSending} />
    </div>
  );
}

export default App;
