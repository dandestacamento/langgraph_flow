import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

import { reportClientError } from "../api/client";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches render-time crashes anywhere below it, shows a recoverable
 * fallback instead of a white screen, and reports the error to the
 * backend's POST /client-error (chat-ui-plan1.md section 2.7) - which
 * logs it server-side, ready to flow into Grafana/Loki once that stack
 * (routing-lab-prod-plan.md section 2.5) is live. A class component
 * because React only exposes getDerivedStateFromError/componentDidCatch
 * on classes - there is no hook equivalent.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    void reportClientError({
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack ?? undefined,
    });
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="mx-auto flex h-dvh max-w-md flex-col justify-center gap-3 p-6">
          <h1 className="text-lg font-semibold text-slate-900">Something went wrong</h1>
          <p className="text-sm text-slate-600">
            The error has been reported. Reloading usually fixes it - your conversation history is
            saved on the server and will still be here.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="self-start rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
