import { useCallback, useEffect, useState } from 'react';
import { license, type LicenseStatus } from '@/lib/api';

interface UseLicenseResult {
  status: LicenseStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Fetches the current license status and listens for 402 events dispatched
 * by the API client (see api/_monolith.ts `license-gate-triggered`). Used
 * by <LicenseGate> at the top of the tree to decide whether to render the
 * app or the activation wizard.
 */
export function useLicense(): UseLicenseResult {
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await license.status();
      setStatus(s);
    } catch (e: any) {
      setError(e?.message ?? 'failed to fetch license status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const handler = () => {
      refresh();
    };
    window.addEventListener('license-gate-triggered', handler);
    return () => window.removeEventListener('license-gate-triggered', handler);
  }, [refresh]);

  return { status, loading, error, refresh };
}
