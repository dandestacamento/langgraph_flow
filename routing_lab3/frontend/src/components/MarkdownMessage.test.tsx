import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownMessage } from "./MarkdownMessage";

describe("MarkdownMessage", () => {
  it("renders basic Markdown formatting", () => {
    const { container } = render(
      <MarkdownMessage content={"**Important**: check the filter.\n\n- Step one\n- Step two"} />,
    );
    expect(screen.getByText("Important")).toBeInTheDocument();
    expect(container.querySelector("strong")).not.toBeNull();
    expect(container.textContent).toContain("Important: check the filter.");
    expect(screen.getByText("Step one")).toBeInTheDocument();
    expect(screen.getByText("Step two")).toBeInTheDocument();
  });

  it("sanitizes raw HTML instead of rendering it as live markup", () => {
    const { container } = render(
      <MarkdownMessage content={'<img src=x onerror="window.__pwned = true">normal text'} />,
    );
    // rehype-sanitize must strip the dangerous element/attribute - no
    // <img> (and therefore no onerror handler) should ever reach the DOM.
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/normal text/)).toBeInTheDocument();
  });
});
