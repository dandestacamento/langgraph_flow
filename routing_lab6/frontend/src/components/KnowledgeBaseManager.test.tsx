import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeDocument } from "../api/client";
import KnowledgeBaseManager from "./KnowledgeBaseManager";

vi.mock("../api/client", () => ({
  listKnowledgeDocuments: vi.fn(),
  getKnowledgeDocument: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
  overrideClassification: vi.fn(),
  fetchKnowledgeTaxonomy: vi.fn(),
}));

import {
  fetchKnowledgeTaxonomy,
  getKnowledgeDocument,
  listKnowledgeDocuments,
  overrideClassification,
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
});
