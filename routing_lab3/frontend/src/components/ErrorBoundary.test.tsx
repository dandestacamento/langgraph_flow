import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { ErrorBoundary } from "./ErrorBoundary";

vi.mock("../api/client");

const mockedReportClientError = vi.mocked(client.reportClientError);

function Crashing(): never {
  throw new Error("Deliberate render crash");
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedReportClientError.mockResolvedValue(undefined);
  // React logs caught boundary errors via console.error - expected
  // noise for these tests, not a failure signal.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("renders its children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("All good")).toBeInTheDocument();
  });

  it("shows the fallback and reports the error when a child crashes", async () => {
    render(
      <ErrorBoundary>
        <Crashing />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();

    await waitFor(() =>
      expect(mockedReportClientError).toHaveBeenCalledWith(
        expect.objectContaining({ message: "Deliberate render crash" }),
      ),
    );
  });
});
