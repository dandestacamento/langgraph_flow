import Keycloak from "keycloak-js";

/**
 * OIDC login against the Keycloak realm set up in
 * routing_lab6/infra/keycloak (see its README) - per
 * instructions/learnings/chat-ui-plan1.md section 2.3/Phase D. A single
 * module-level instance, matching keycloak-js's own recommended usage
 * pattern (one instance per page load, not one per component).
 */
const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8081",
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "routing-lab6",
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "routing-lab6-frontend",
});

export default keycloak;

/**
 * Initializes Keycloak with `onLoad: "login-required"` - the whole app
 * is a protected route; an unauthenticated visitor is redirected to
 * Keycloak's own login page before anything renders. Call once, before
 * the first render (see main.tsx).
 */
export async function initKeycloak(): Promise<boolean> {
  return keycloak.init({
    onLoad: "login-required",
    pkceMethod: "S256",
  });
}

/**
 * Returns a fresh access token, refreshing it first if it's within 30
 * seconds of expiring - keycloak-js's own recommended pattern, used
 * instead of reading `keycloak.token` directly and risking a request
 * going out with a token that's about to (or just did) expire.
 *
 * If the refresh itself fails (the SSO session/refresh token has
 * expired - e.g. the tab sat idle past the realm's session timeout),
 * redirects through Keycloak's login page rather than surfacing a
 * cryptic error banner the Retry button can never fix. Nothing is lost:
 * conversation history lives server-side and is restored after login.
 */
export async function getValidToken(): Promise<string> {
  try {
    await keycloak.updateToken(30);
  } catch {
    await keycloak.login();
    throw new Error("Session expired - redirecting to sign-in…");
  }
  if (!keycloak.token) {
    await keycloak.login();
    throw new Error("Session expired - redirecting to sign-in…");
  }
  return keycloak.token;
}
