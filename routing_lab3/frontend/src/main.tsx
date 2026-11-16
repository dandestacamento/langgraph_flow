import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";
import { initKeycloak } from "./auth/keycloak";
import "./index.css";

const rootElement = document.getElementById("root")!;
const root = createRoot(rootElement);

// The whole app is a protected route (initKeycloak uses
// onLoad: "login-required") - nothing renders until Keycloak either
// confirms an existing session or redirects through its own login page
// and back. See src/auth/keycloak.ts.
initKeycloak()
  .then((authenticated) => {
    if (!authenticated) {
      // "login-required" means init() only resolves once logged in -
      // reaching here with `false` is an unexpected state, not a normal
      // "not logged in yet" one (that redirects instead of resolving).
      throw new Error("Keycloak authentication failed unexpectedly.");
    }
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  })
  .catch((error: unknown) => {
    root.render(
      <div style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
        <h1>Authentication error</h1>
        <p>{error instanceof Error ? error.message : String(error)}</p>
      </div>,
    );
  });
