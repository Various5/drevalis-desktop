import { Link, useLocation } from 'react-router-dom';
import { Compass } from 'lucide-react';

// ---------------------------------------------------------------------------
// 404 page
// ---------------------------------------------------------------------------
//
// Renders inside <Layout> so the chrome (sidebar, header, activity bar)
// stays in place — the user can navigate elsewhere without a reload.

export default function NotFound() {
  const location = useLocation();
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-5 text-center">
      <div className="w-12 h-12 rounded-full bg-bg-elevated border border-border flex items-center justify-center text-txt-secondary">
        <Compass size={20} />
      </div>
      <div>
        <h2 className="text-lg font-display font-semibold text-txt-primary mb-1">
          Page not found
        </h2>
        <p className="text-xs text-txt-secondary max-w-md">
          The route <code className="inline">{location.pathname}</code> doesn&apos;t match anything in this app.
        </p>
      </div>
      <Link
        to="/"
        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-accent text-txt-onAccent text-sm font-medium hover:bg-accent-hover transition-colors"
      >
        Back to dashboard
      </Link>
    </div>
  );
}
