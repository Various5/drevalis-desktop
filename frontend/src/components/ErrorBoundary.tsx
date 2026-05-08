import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

// ---------------------------------------------------------------------------
// Top-level Error Boundary
// ---------------------------------------------------------------------------
//
// Wraps the lazy <Suspense> island in App.tsx. Lazy-import failures (CDN
// hiccup, stale chunk after a deploy, transient network blip) used to
// blank the whole app; now we render a small "something broke" surface
// with a Reload button and log the error so it's visible in devtools.
//
// Phase 1.8 acceptance: throw inside any page during dev — the
// boundary catches it, the rest of the app still works (the chrome
// stays around because the boundary is INSIDE the providers but OUTSIDE
// the Suspense + Routes region).

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface to the devtools console so devs see the stack;
    // structlog-equivalent telemetry can hook in here later.
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="flex flex-col items-center justify-center min-h-[60vh] gap-4 p-8 text-center"
        >
          <div className="w-12 h-12 rounded-full bg-error/10 border border-error/30 flex items-center justify-center text-error">
            <AlertTriangle size={20} />
          </div>
          <div>
            <h2 className="text-lg font-display font-semibold text-txt-primary mb-1">
              Something broke. Reload the page.
            </h2>
            <p className="text-xs text-txt-secondary max-w-md">
              {this.state.error?.message ?? 'An unexpected error occurred while loading this view.'}
            </p>
          </div>
          <button
            type="button"
            onClick={this.handleReload}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-accent text-txt-onAccent text-sm font-medium hover:bg-accent-hover transition-colors"
          >
            <RefreshCw size={14} />
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export { ErrorBoundary };
