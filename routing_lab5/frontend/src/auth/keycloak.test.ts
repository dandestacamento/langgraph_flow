import { beforeEach, describe, expect, it, vi } from "vitest";

const instance = vi.hoisted(() => ({
  init: vi.fn(),
  login: vi.fn().mockResolvedValue(undefined),
  updateToken: vi.fn(),
  token: undefined as string | undefined,
}));

vi.mock("keycloak-js", () => ({
  // A `function` (not arrow) so `new Keycloak(...)` works - constructors
  // returning an object yield that object.
  default: vi.fn(function Keycloak() {
    return instance;
  }),
}));

import { getValidToken } from "./keycloak";

beforeEach(() => {
  vi.clearAllMocks();
  instance.token = undefined;
});

describe("getValidToken", () => {
  it("returns the token after a successful refresh", async () => {
    instance.updateToken.mockResolvedValue(true);
    instance.token = "fresh-token";

    await expect(getValidToken()).resolves.toBe("fresh-token");
    expect(instance.login).not.toHaveBeenCalled();
  });

  it("redirects through Keycloak login when the session has expired", async () => {
    // updateToken rejecting = the refresh token/SSO session is gone -
    // the exact mid-use expiry found during live testing.
    instance.updateToken.mockRejectedValue(new Error("Refresh token expired"));

    await expect(getValidToken()).rejects.toThrow(/Session expired/);
    expect(instance.login).toHaveBeenCalled();
  });
});
