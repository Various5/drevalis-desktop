import { useEffect, useState } from 'react';
import { auth } from '@/lib/api';
import { useAuthContext, type AuthContextValue } from '@/lib/AuthContext';

// ---------------------------------------------------------------------------
// useAuth — thin wrapper around AuthContext (Phase 2.2)
// ---------------------------------------------------------------------------
//
// Pre-2.2: every caller of useAuth() fired its own /auth/me request,
// and LoginGate fetched a second time. Now this hook just reads from
// the single AuthProvider mounted at App.tsx, so the cold-start
// network tab shows ONE /auth/me, not two-or-more.

export type UseAuthResult = AuthContextValue;

export function useAuth(): UseAuthResult {
  return useAuthContext();
}

// ────────────────────────────────────────────────────────────────────

interface UseAuthModeResult {
  teamMode: boolean;
  demoMode: boolean;
  ready: boolean;
}

/**
 * Fetches /api/v1/auth/mode once on mount. Cached in module scope after
 * the first successful call so repeated renders don't re-fetch.
 */
let _cachedMode: { teamMode: boolean; demoMode: boolean } | null = null;
let _modePromise: Promise<{ teamMode: boolean; demoMode: boolean }> | null = null;

export function useAuthMode(): UseAuthModeResult {
  const [state, setState] = useState<UseAuthModeResult>({
    teamMode: _cachedMode?.teamMode ?? false,
    demoMode: _cachedMode?.demoMode ?? false,
    ready: _cachedMode !== null,
  });

  useEffect(() => {
    if (_cachedMode) return;
    if (!_modePromise) {
      _modePromise = auth
        .mode()
        .then((m) => {
          const resolved = { teamMode: m.team_mode, demoMode: m.demo_mode ?? false };
          _cachedMode = resolved;
          return resolved;
        })
        .catch(() => {
          const fallback = { teamMode: false, demoMode: false };
          _cachedMode = fallback;
          return fallback;
        });
    }
    let alive = true;
    void _modePromise.then((m) => {
      if (alive) setState({ ...m, ready: true });
    });
    return () => {
      alive = false;
    };
  }, []);

  return state;
}
