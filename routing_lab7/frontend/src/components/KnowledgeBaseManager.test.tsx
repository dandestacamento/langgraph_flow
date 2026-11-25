import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeDocument } from "../api/client";
import KnowledgeBaseManager from "./KnowledgeBaseManager";

vi.mock("../api/client", () => ({
  listKnowledgeDocuments: vi.fn(),
  getKnowledgeDocument: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
  overrideClassification: vi.fn(),
  reindexKnowledgeDocument: vi.fn(),
  refreshClassificationSuggestion: vi.fn(),
  fetchKnowledgeTaxonomy: vi.fn(),
}));

import {
  fetchKnowledgeTaxonomy,
  getKnowledgeDocument,
  listKnowledgeDocuments,
  overrideClassification,
  reindexKnowledgeDocument,
  refreshClassificationSuggestion,
  uploadKnowledgeDocument,
} from "../api/client";

const TAXONOMY = {
  appliances: ["refrigerators", "washing_machines"],
  finance: ["budgeting", "loans"],
};

function doc(overrides: Partial<KnowledgeDocument> = {}): KnowledgeDocument {
  return {
    document_id: "doc-1",
    filename: "bulletin.md",
    media_type: "text/markdown",
    size_bytes: 2048,
    version: 1,
    status: "indexed",
    topic: "appliances",
    subtopic: "washing_machines",
    chapters: ["maintenance"],
    classification_confidence: 0.92,
    error: null,
    chunk_count: 3,
    chunk_ids: ["doc-1:v1:0", "doc-1:v1:1", "doc-1:v1:2"],
    events: [{ node: "classify", elapsed_ms: 812, detail: "appliances/washing_machines" }],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:05Z",
    duplicate: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchKnowledgeTaxonomy).mockResolvedValue(TAXONOMY);
  vi.mocked(listKnowledgeDocuments).mockResolvedValue([]);
});

describe("KnowledgeBaseManager", () => {
  it("lists ingested documents with their status badge and classification", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([
      doc(),
      doc({ document_id: "doc-2", filename: "notes.pdf", status: "failed", topic: null, subtopic: null }),
    ]);

    render(<KnowledgeBaseManager />);

    expect(await screen.findByText("bulletin.md")).toBeInTheDocument();
    expect(screen.getByText("Indexed")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/appliances\/washing_machines/)).toBeInTheDocument();
  });

  it("uploads a picked file and shows the new document expanded", async () => {
    const uploaded = doc({ document_id: "doc-3", filename: "new.md", status: "processing" });
    vi.mocked(uploadKnowledgeDocument).mockResolvedValue(uploaded);

    render(<KnowledgeBaseManager />);
    await screen.findByText(/No documents ingested yet/);

    const input = screen.getByLabelText("Choose documents to ingest");
    fireEvent.change(input, {
      target: { files: [new File(["# hi"], "new.md", { type: "text/markdown" })] },
    });

    expect(await screen.findByText("new.md")).toBeInTheDocument();
    expect(uploadKnowledgeDocument).toHaveBeenCalledOnce();
    // Expanded detail view shows the pipeline log for the new upload.
    expect(screen.getByText("Pipeline log")).toBeInTheDocument();
  });

  it("polls processing documents until their status settles", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc({ status: "processing" })]);
      vi.mocked(getKnowledgeDocument).mockResolvedValue(doc({ status: "indexed" }));

      render(<KnowledgeBaseManager />);
      // Flush the initial load without real timers.
      await vi.waitFor(() => {
        expect(screen.getByText("Processing")).toBeInTheDocument();
      });

      await vi.advanceTimersByTimeAsync(2100);
      expect(getKnowledgeDocument).toHaveBeenCalledWith("doc-1");
      await vi.waitFor(() => {
        expect(screen.getByText("Indexed")).toBeInTheDocument();
      });

      // Settled - no further polls fire.
      vi.mocked(getKnowledgeDocument).mockClear();
      await vi.advanceTimersByTimeAsync(4200);
      expect(getKnowledgeDocument).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers a manual classification override for needs_review documents", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([
      doc({
        status: "needs_review",
        topic: null,
        subtopic: null,
        classification_confidence: null,
        error: "Unknown topic 'cooking'.",
        chunk_count: 0,
      }),
    ]);
    vi.mocked(overrideClassification).mockResolvedValue(doc({ status: "processing" }));

    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));

    expect(screen.getByText("Unknown topic 'cooking'.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Topic/), { target: { value: "appliances" } });
    fireEvent.change(screen.getByLabelText(/Subtopic/), {
      target: { value: "washing_machines" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reclassify & index" }));

    await waitFor(() => {
      expect(overrideClassification).toHaveBeenCalledWith(
        "doc-1",
        "appliances",
        "washing_machines",
        false,
      );
    });
    // The override's response (back to processing) replaces the row.
    expect(await screen.findByText("Processing")).toBeInTheDocument();
  });

  it("does not show the override form for indexed documents", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc()]);

    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));

    expect(screen.getByText("Pipeline log")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reclassify & index" })).not.toBeInTheDocument();
  });

  it("re-indexes the stored file without uploading it again", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc()]);
    vi.mocked(reindexKnowledgeDocument).mockResolvedValue(doc({
      status: "processing",
      pending: { version: 2, topic: null, subtopic: null, classification_confidence: null },
    }));
    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));
    fireEvent.click(screen.getByRole("button", { name: "Re-index stored file" }));
    await waitFor(() => expect(reindexKnowledgeDocument).toHaveBeenCalledWith("doc-1"));
    expect(await screen.findByText(/Version 1 remains indexed while replacement version 2/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-index stored file" })).not.toBeInTheDocument();
  });

  it("shows a re-index error without losing the indexed document", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc()]);
    vi.mocked(reindexKnowledgeDocument).mockRejectedValue(new Error("Stored original unavailable"));
    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));
    fireEvent.click(screen.getByRole("button", { name: "Re-index stored file" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Stored original unavailable");
    expect(screen.getByText("Indexed")).toBeInTheDocument();
  });

  it("approves a new suggested topic and subtopic", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([
      doc({ status: "needs_review", topic: "artificial_intelligence", subtopic: "risk_management" }),
    ]);
    vi.mocked(overrideClassification).mockResolvedValue(doc({ status: "processing" }));
    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));
    fireEvent.click(screen.getByRole("button", { name: "Approve suggestion & index" }));
    await waitFor(() => expect(overrideClassification).toHaveBeenCalledWith(
      "doc-1", "artificial_intelligence", "risk_management", true,
    ));
  });

  it("lets a user create a subtopic under an existing topic", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc({ status: "needs_review" })]);
    vi.mocked(overrideClassification).mockResolvedValue(doc({ status: "processing" }));
    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create subtopic" }));
    fireEvent.change(screen.getByLabelText("New subtopic"), { target: { value: "ovens" } });
    fireEvent.click(screen.getByRole("button", { name: "Reclassify & index" }));
    await waitFor(() => expect(overrideClassification).toHaveBeenCalledWith("doc-1", "appliances", "ovens", true));
  });

  it("lets a user create a topic and subtopic", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc({ status: "needs_review" })]);
    vi.mocked(overrideClassification).mockResolvedValue(doc({ status: "processing" }));
    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create topic" }));
    fireEvent.change(screen.getByLabelText("New topic"), { target: { value: "artificial_intelligence" } });
    fireEvent.change(screen.getByLabelText("New subtopic"), { target: { value: "risk_management" } });
    fireEvent.click(screen.getByRole("button", { name: "Reclassify & index" }));
    await waitFor(() => expect(overrideClassification).toHaveBeenCalledWith(
      "doc-1", "artificial_intelligence", "risk_management", true,
    ));
  });

  it("refreshes a suggestion for an already parked document", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc({ status: "needs_review" })]);
    vi.mocked(refreshClassificationSuggestion).mockResolvedValue(doc({ status: "processing" }));
    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));
    fireEvent.click(screen.getByRole("button", { name: "Get a fresh suggestion" }));
    await waitFor(() => expect(refreshClassificationSuggestion).toHaveBeenCalledWith("doc-1"));
    expect(await screen.findByText("Processing")).toBeInTheDocument();
  });

  it("shows the published version and replacement suggestion during review", async () => {
    vi.mocked(listKnowledgeDocuments).mockResolvedValue([doc({
      status: "needs_review",
      version: 1,
      topic: "appliances",
      subtopic: "washing_machines",
      pending: { version: 2, topic: "finance", subtopic: "budgeting", classification_confidence: 0.4 },
    })]);
    vi.mocked(overrideClassification).mockResolvedValue(doc({ status: "processing" }));
    render(<KnowledgeBaseManager />);
    fireEvent.click(await screen.findByRole("button", { name: /bulletin\.md/ }));
    expect(screen.getByText(/Version 1 remains indexed while replacement version 2/)).toBeInTheDocument();
    expect(screen.getByText("finance / budgeting")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve suggestion & index" }));
    await waitFor(() => expect(overrideClassification).toHaveBeenCalledWith(
      "doc-1", "finance", "budgeting", false,
    ));
  });

  it("reports an uploaded replacement while keeping the published version", async () => {
    vi.mocked(uploadKnowledgeDocument).mockResolvedValue(doc({
      status: "processing",
      pending: { version: 2, topic: null, subtopic: null, classification_confidence: null },
    }));
    render(<KnowledgeBaseManager />);
    await screen.findByText(/No documents ingested yet/);
    fireEvent.change(screen.getByLabelText("Choose documents to ingest"), {
      target: { files: [new File(["updated"], "bulletin.md", { type: "text/markdown" })] },
    });
    expect(await screen.findByText(/previous version remains indexed/)).toBeInTheDocument();
  });
});
