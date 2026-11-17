import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PassagePreview } from "./PassagePreview";
import type { SelectedPassage } from "./PassagePreview";

const PASSAGE: SelectedPassage = {
  topic: "appliances",
  subtopic: "washing_machines",
  chapter_id: "chapter_03_faults",
  document_id: "doc1",
  score: 0.79,
  text: "E21: Drainage problem. Check the pump filter and drain hose for blockages.",
};

describe("PassagePreview", () => {
  it("shows the passage's full text and metadata", () => {
    render(<PassagePreview passage={PASSAGE} onClose={() => {}} />);

    expect(screen.getByRole("dialog", { name: /chapter_03_faults/ })).toBeInTheDocument();
    expect(screen.getByText("appliances › washing_machines")).toBeInTheDocument();
    expect(screen.getByText("doc1")).toBeInTheDocument();
    expect(screen.getByText(/0\.79 \(lower = closer match\)/)).toBeInTheDocument();
    expect(screen.getByText(/E21: Drainage problem\. Check the pump filter/)).toBeInTheDocument();
  });

  it("closes via the button, the backdrop, and Escape", () => {
    const onClose = vi.fn();
    render(<PassagePreview passage={PASSAGE} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Close source preview" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
