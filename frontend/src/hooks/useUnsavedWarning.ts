import { useEffect } from 'react';

/**
 * Shows a browser "unsaved changes" warning when the user tries to navigate
 * away or close the tab while there are unsaved modifications.
 */
export function useUnsavedWarning(hasUnsaved: boolean) {
  useEffect(() => {
    if (!hasUnsaved) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasUnsaved]);
}
