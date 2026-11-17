import { useCallback, useEffect, useState } from "react";

import keycloak from "../auth/keycloak";

const WARN_BEFORE_EXPIRY_MS = 2 * 60 * 1000;
const CHECK_INTERVAL_MS = 30 * 1000;

/**
 * Warns shortly before the Keycloak session (refresh token) expires, so
 * the user can extend it with one click instead of being redirected to
 * the login page mid-conversation (chat-ui-plan3.md §1.6 - the
 * follow-on to the mid-use-expiry redirect fix). `staySignedIn` forces
 * a token refresh, which extends the SSO session's idle timeout.
 */
export function useSessionExpiryWarning() {
  const [showWarning, setShowWarning] = useState(false);

  useEffect(() => {
    function check() {
      const expiresAtSeconds = keycloak.refreshTokenParsed?.exp;
      if (!expiresAtSeconds) return;
      const msLeft = expiresAtSeconds * 1000 - Date.now();
      setShowWarning(msLeft > 0 && msLeft < WARN_BEFORE_EXPIRY_MS);
    }
    const interval = setInterval(check, CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const staySignedIn = useCallback(async () => {
    try {
      // -1 forces a refresh regardless of the access token's remaining
      // validity - the refresh issues a new refresh token, pushing the
      // session's idle expiry out again.
      await keycloak.updateToken(-1);
      setShowWarning(false);
    } catch {
      // Refresh genuinely failed (session already gone) - the next API
      // call's getValidToken() handles the login redirect.
      setShowWarning(false);
    }
  }, []);

  return { showWarning, staySignedIn };
}
