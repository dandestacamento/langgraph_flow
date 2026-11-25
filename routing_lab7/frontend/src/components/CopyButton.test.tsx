import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CopyButton } from "./CopyButton";

let writeTextMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  writeTextMock = vi.fn().mockResolvedValue(undefined);
  // jsdom's own (partial/throwing) Clipboard implementation makes
  // Object.assign unreliable here - defineProperty guarantees the
  // override actually takes effect. Uses fireEvent (not userEvent)
  // below, since userEvent.setup() installs its own clipboard stub that
  // would otherwise override this one.
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: writeTextMock },
    configurable: true,
  });
});

describe("CopyButton", () => {
  it("copies the given text and shows a transient confirmation", async () => {
    render(<CopyButton text="E21 is a drainage fault." />);

    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));

    await waitFor(() => expect(writeTextMock).toHaveBeenCalledWith("E21 is a drainage fault."));
    expect(await screen.findByText("Copied")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("Copy"), { timeout: 2000 });
  });
});
