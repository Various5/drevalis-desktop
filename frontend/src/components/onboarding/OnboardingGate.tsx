import { useCallback, useEffect, useState } from 'react';
import { onboarding as onboardingApi, type OnboardingStatus } from '@/lib/api';
import { OnboardingWizard } from './OnboardingWizard';

/**
 * Polls /api/v1/onboarding/status on mount + every 30s and mounts the
 * wizard when `should_show` is true. Failures are silent — if the
 * backend is down the wizard just doesn't appear, which is the right
 * behaviour (the LicenseGate and error boundaries handle the real
 * messaging).
 */
export function OnboardingGate() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await onboardingApi.status();
      setStatus(s);
    } catch {
      // Backend not ready / license not active / etc. — no-op.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  if (!status || !status.should_show) return null;

  return (
    <OnboardingWizard
      status={status}
      onRefresh={refresh}
      onDismiss={refresh}
    />
  );
}

export default OnboardingGate;
