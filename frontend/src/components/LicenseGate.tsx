import { type ReactNode } from 'react';
import { Spinner } from '@/components/ui/Spinner';
import { useLicense } from '@/lib/useLicense';
import { useAuthMode } from '@/lib/useAuth';
import { ActivationWizard } from '@/pages/Activation/ActivationWizard';

interface Props {
  children: ReactNode;
}

/**
 * Top-level license gate.
 *
 * - loading      → spinner
 * - unactivated  → <ActivationWizard>
 * - expired      → <ActivationWizard state="expired">
 * - invalid      → <ActivationWizard state="invalid">
 * - grace        → render children with a banner prepended
 * - active       → render children
 *
 * Demo mode (``/auth/mode.demo_mode === true``) bypasses the gate
 * entirely — the demo install is public by design and has no licence
 * to activate. The backend licence middleware also skips in demo mode.
 */
export function LicenseGate({ children }: Props) {
  const { status, loading, error, refresh } = useLicense();
  const { demoMode, ready: modeReady } = useAuthMode();

  if (modeReady && demoMode) {
    return <>{children}</>;
  }

  if ((loading && !status) || !modeReady) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-base">
        <Spinner size="lg" />
      </div>
    );
  }

  // Network error reaching /api/v1/license/status. Still show children —
  // user may be developing offline; backend is unreachable for some other
  // reason. The top bar in active pages will surface the disconnect.
  if (error && !status) {
    return <>{children}</>;
  }

  if (!status) {
    return <>{children}</>;
  }

  if (
    status.state === 'unactivated' ||
    status.state === 'expired' ||
    status.state === 'invalid'
  ) {
    return (
      <ActivationWizard
        status={status.state}
        stateError={status.error}
        machineId={status.machine_id}
        onActivated={refresh}
      />
    );
  }

  if (status.state === 'grace' && status.period_end) {
    const periodEnd = new Date(status.period_end);
    const now = new Date();
    const daysLeft = Math.max(
      0,
      Math.ceil((periodEnd.getTime() - now.getTime()) / (24 * 60 * 60 * 1000)) + 7,
    );
    return (
      <>
        <div className="bg-amber-500/10 border-b border-amber-500/30 text-amber-200 text-xs px-4 py-2 text-center">
          Your license expired on {periodEnd.toLocaleDateString()} — running in grace period.
          Renew within {daysLeft} days to keep the app working.
        </div>
        {children}
      </>
    );
  }

  return <>{children}</>;
}
