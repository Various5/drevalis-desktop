// Frontend crash telemetry. Mirrors the Python side: gated on a DSN
// + an enabled flag, both supplied by the backend at bootstrap time
// (the SPA fetches /api/v1/telemetry/bootstrap on load).
//
// Why we don't bake the DSN into the bundle: it lets the operator
// flip the destination without re-shipping the frontend (self-host
// Glitchtip, switch to Sentry SaaS, point at staging). The
// "fetch then init" dance costs one round trip on startup; in
// return we get a single source of truth for telemetry config.

// ``@sentry/browser`` is statically imported so rollup can tree-shake to just
// ``Sentry.init`` (the only call site). We tried a dynamic import to keep it
// off the critical bundle, but it defeated tree-shaking — the whole module
// surface was retained, ballooning vendor by ~370 kB. The Sentry SDK is
// instead routed into its own ``vendor-sentry`` chunk via manualChunks in
// vite.config.ts, so it ships separately while staying tree-shaken.

import * as Sentry from '@sentry/browser';

export type TelemetryBootstrap = {
  dsn: string | null;
  enabled: boolean;
  environment: string;
  release: string | null;
};

let initialised = false;

export async function initTelemetry(): Promise<boolean> {
  if (initialised) return true;

  let bootstrap: TelemetryBootstrap;
  try {
    const res = await fetch('/api/v1/telemetry/bootstrap', { credentials: 'include' });
    if (!res.ok) return false;
    bootstrap = (await res.json()) as TelemetryBootstrap;
  } catch {
    // Backend not reachable yet — telemetry is best-effort; never
    // block the SPA from rendering if /telemetry/bootstrap fails.
    return false;
  }

  if (!bootstrap.enabled || !bootstrap.dsn) return false;

  Sentry.init({
    dsn: bootstrap.dsn,
    environment: bootstrap.environment,
    release: bootstrap.release ?? undefined,
    // Hard PII off — same posture as the backend SDK. The desktop
    // user is the operator AND the data subject, so we lean
    // conservative by default and let them opt in to more breadth
    // later.
    sendDefaultPii: false,
    // No perf tracing yet (volume goldilocks: it adds a lot of events
    // for a small repo). Enable later when investigating slow nav.
    tracesSampleRate: 0,
    // Tag every event so the Glitchtip dashboard can split
    // backend vs frontend at a glance.
    initialScope: {
      tags: { component: 'frontend' },
    },
    // Belt-and-suspenders client-side redaction. The breadcrumbs
    // shouldn't contain Authorization headers in the first place,
    // but this scrubs them if they sneak in via custom fetch
    // wrappers.
    beforeBreadcrumb(crumb) {
      const data = crumb.data;
      if (data && typeof data === 'object') {
        for (const key of Object.keys(data)) {
          if (/authorization|cookie|x-api-key|license/i.test(key)) {
            (data as Record<string, unknown>)[key] = '[REDACTED]';
          }
        }
      }
      return crumb;
    },
  });

  initialised = true;
  return true;
}
