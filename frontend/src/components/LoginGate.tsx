import { useEffect, useState, type ReactNode } from 'react';
import { Spinner } from '@/components/ui/Spinner';
import { useAuth, useAuthMode } from '@/lib/useAuth';

/**
 * Gatekeeps the app routes behind the team-mode login check.
 *
 * - If `/auth/me` returns a user → render children.
 * - If `/auth/me` returns null AND `/auth/mode.team_mode` is true →
 *   redirect to `/login`.
 * - Otherwise (no users + no OWNER_EMAIL env) → render children.
 *
 * Phase 2.2: consumes the shared AuthContext + useAuthMode instead
 * of issuing its own ``auth.me()`` call. Cold-start network tab now
 * shows ONE ``/auth/me`` request, not two.
 *
 * The gate must NOT be applied to the `/login` route itself —
 * mount it inside the `<Layout>` branch of the router.
 */
export function LoginGate({ children }: { children: ReactNode }) {
  const { user, ready: authReady } = useAuth();
  const { teamMode, ready: modeReady } = useAuthMode();
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    // Wait for both calls to settle before deciding. Otherwise we'd
    // briefly think the user is unauthenticated and redirect even
    // when team_mode is false.
    if (!authReady || !modeReady) return;
    if (user === null && teamMode) {
      setRedirecting(true);
      window.location.href = '/login';
    }
  }, [authReady, modeReady, user, teamMode]);

  const settling = !authReady || !modeReady || redirecting;
  if (settling) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-bg-base">
        <Spinner size="lg" />
      </div>
    );
  }
  return <>{children}</>;
}
