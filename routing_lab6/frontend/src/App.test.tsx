import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";
import { useChat } from "./hooks/useChat";

vi.mock("./hooks/useChat");

// KnowledgeBaseManager (lazy-loaded) fetches documents/taxonomy on mount;
// stub those out, plus App's own uploadAttachment, so rendering it doesn't
// hit the network.
vi.mock("./api/client", () => ({
  uploadAttachment: vi.fn(),
  listKnowledgeDocuments: vi.fn().mockResolvedValue([]),
  getKnowledgeDocument: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
  overrideClassification: vi.fn(),
  fetchKnowledgeTaxonomy: vi.fn().mockResolvedValue({}),
}));

const mockedUseChat = vi.mocked(useChat);

function baseChatState() {
  return {
    threadId: "t1",
    threads: [
      { thread_id: "t1", title: "First conversation", updated_at: new Date().toISOString() },
      { thread_id: "t2", title: "Second conversation", updated_at: new Date().toISOString() },
    ],
    messages: [],
    isSending: false,
    isLoadingHistory: false,
    error: null,
    recentlyDeleted: null,
    sendMessage: vi.fn(),
    stopStreaming: vi.fn(),
    retryLastMessage: vi.fn(),
    regenerateLastTurn: vi.fn(),
    newConversation: vi.fn(),
    switchConversation: vi.fn(),
    renameConversation: vi.fn(),
    deleteConversation: vi.fn(),
    undoDelete: vi.fn(),
  };
}

describe("App", () => {
  it("uses a topic-neutral app title while preserving the conversation title", () => {
    mockedUseChat.mockReturnValue(baseChatState());
    const { rerender } = render(<App />);
    expect(screen.getByRole("heading", { name: "Knowledge Base Chat" })).toBeInTheDocument();
    expect(document.title).toBe("First conversation - Knowledge Base Chat");

    mockedUseChat.mockReturnValue({ ...baseChatState(), threadId: "" });
    rerender(<App />);
    expect(document.title).toBe("Knowledge Base Chat");
  });

  it("switches back to the chat view when a conversation is selected from the Knowledge base screen", async () => {
    const chatState = baseChatState();
    mockedUseChat.mockReturnValue(chatState);
    render(<App />);

    // Navigate to the Knowledge base screen (chat view -> knowledge view).
    fireEvent.click(screen.getByRole("button", { name: "Knowledge base" }));
    expect(await screen.findByRole("button", { name: "Back to chat" })).toBeInTheDocument();

    // Selecting a past conversation from the sidebar must both switch the
    // conversation AND bring the user back to the chat view - previously
    // only the former happened, leaving the Knowledge base screen stuck up.
    const conversationButton = await screen.findByText("Second conversation");
    fireEvent.click(conversationButton);

    expect(chatState.switchConversation).toHaveBeenCalledWith("t2");
    expect(await screen.findByRole("button", { name: "Knowledge base" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back to chat" })).not.toBeInTheDocument();
  });

  it("switches back to the chat view when starting a new conversation from the Knowledge base screen", async () => {
    const chatState = baseChatState();
    mockedUseChat.mockReturnValue(chatState);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Knowledge base" }));
    expect(await screen.findByRole("button", { name: "Back to chat" })).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "+ New conversation" }));

    expect(chatState.newConversation).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Knowledge base" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back to chat" })).not.toBeInTheDocument();
  });
});
