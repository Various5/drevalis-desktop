import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { auth, type AuthUser } from '@/lib/api';

// ---------------------------------------------------------------------------
// Auth context
// ---------------------------------------------------------------------------
//
// Single owner of the ``/api/v1/auth/me`` request. Pre-Phase-2.2 every
// caller of ``useAuth()`` fetched independently, and ``LoginGate``
// fetched a second time directly via ``auth.me()``. On a cold start
// the network tab showed two requests; on every component re-render
// where ``useAuth()`` was called fresh you got more.
//
// Now: ``<AuthProvider>`` wraps the app once at the App.tsx level.
// One mount → one ``auth.me()`` request. Children consume via
// ``useAuth()`` (renamed wrapper around ``useContext``). LoginGate
// calls the same hook instead of issuing its own request.

export interface AuthContextValue {
  user: AuthUser | null;
  /** True while the very first ``auth.me()`` is in flight. */
  loading: boolean;
  /** True once the first ``auth.me()`` resolves or rejects. */
  ready: boolean;
  /** Re-fetch the current user (used after login / logout). */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const me = await auth.me();
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Listen for the custom "auth:refresh" event dispatched by TwoFactorSection
  // after enabling / disabling 2FA so totp_enabled reflects the new state.
  useEffect(() => {
    const handler = () => { void refresh(); };
    window.addEventListener('auth:refresh', handler);
    return () => window.removeEventListener('auth:refresh', handler);
  }, [refresh]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, ready, refresh }),
    [user, loading, ready, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Read the current auth state. Must be called inside ``<AuthProvider>``.
 * Pages that need to refresh after a login/logout call ``refresh()``.
 */
export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error('useAuthContext must be used inside <AuthProvider>');
  }
  return ctx;
}
