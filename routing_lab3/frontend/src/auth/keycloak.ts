import Keycloak from "keycloak-js";

/**
 * OIDC login against the Keycloak realm set up in
 * routing_lab3/infra/keycloak (see its README) - per
 * instructions/learnings/chat-ui-plan1.md section 2.3/Phase D. A single
 * module-level instance, matching keycloak-js's own recommended usage
 * pattern (one instance per page load, not one per component).
 */
const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8081",
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "routing-lab3",
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "routing-lab3-frontend",
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
 */
export async function getValidToken(): Promise<string> {
  await keycloak.updateToken(30);
  if (!keycloak.token) {
    throw new Error("Not authenticated.");
  }
  return keycloak.token;
}
