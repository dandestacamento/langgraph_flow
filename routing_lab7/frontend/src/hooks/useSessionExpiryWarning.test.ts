import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const keycloakInstance = vi.hoisted(() => ({
  refreshTokenParsed: undefined as { exp: number } | undefined,
  updateToken: vi.fn(),
}));

vi.mock("../auth/keycloak", () => ({ default: keycloakInstance }));

import { useSessionExpiryWarning } from "./useSessionExpiryWarning";

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  keycloakInstance.refreshTokenParsed = undefined;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useSessionExpiryWarning", () => {
  it("warns once the session is within two minutes of expiring", () => {
    keycloakInstance.refreshTokenParsed = { exp: Math.floor(Date.now() / 1000) + 90 };

    const { result } = renderHook(() => useSessionExpiryWarning());
    expect(result.current.showWarning).toBe(false);

    act(() => {
      vi.advanceTimersByTime(31_000); // first periodic check
    });
    expect(result.current.showWarning).toBe(true);
  });

  it("does not warn while plenty of session time remains", () => {
    keycloakInstance.refreshTokenParsed = { exp: Math.floor(Date.now() / 1000) + 30 * 60 };

    const { result } = renderHook(() => useSessionExpiryWarning());
    act(() => {
      vi.advanceTimersByTime(31_000);
    });
    expect(result.current.showWarning).toBe(false);
  });

  it("staySignedIn forces a token refresh and clears the warning", async () => {
    keycloakInstance.refreshTokenParsed = { exp: Math.floor(Date.now() / 1000) + 60 };
    keycloakInstance.updateToken.mockResolvedValue(true);

    const { result } = renderHook(() => useSessionExpiryWarning());
    act(() => {
      vi.advanceTimersByTime(31_000);
    });
    expect(result.current.showWarning).toBe(true);

    vi.useRealTimers(); // let the async click resolve normally
    await act(async () => {
      await result.current.staySignedIn();
    });
    expect(keycloakInstance.updateToken).toHaveBeenCalledWith(-1);
    await waitFor(() => expect(result.current.showWarning).toBe(false));
  });
});
