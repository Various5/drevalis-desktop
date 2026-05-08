import { Check, CloudOff, Loader2 } from 'lucide-react';

// Small inline indicator that lives next to the breadcrumb and
// reflects the state of the debounced background save. Appears to
// the right of the breadcrumb trail so the user can glance at it
// without leaving the page.

export type AutosaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export function AutosaveStatusPill({ status }: { status: AutosaveStatus }) {
  if (status === 'idle') {
    return (
      <span
        className="hidden sm:inline-flex items-center gap-1.5 text-[11px] text-txt-muted"
        aria-hidden
      >
        Autosave on
      </span>
    );
  }
  if (status === 'saving') {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-bg-elevated border border-border px-2.5 py-1 text-[11px] text-txt-secondary"
        role="status"
        aria-live="polite"
      >
        <Loader2 size={11} className="animate-spin" />
        Saving…
      </span>
    );
  }
  if (status === 'saved') {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-success/10 border border-success/30 px-2.5 py-1 text-[11px] text-success"
        role="status"
        aria-live="polite"
      >
        <Check size={11} />
        Saved
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-error/10 border border-error/30 px-2.5 py-1 text-[11px] text-error"
      role="status"
      aria-live="polite"
    >
      <CloudOff size={11} />
      Save failed
    </span>
  );
}
