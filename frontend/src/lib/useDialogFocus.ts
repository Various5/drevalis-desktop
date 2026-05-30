import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal focus management (Phase 5 a11y).
 *
 * The same trap-Tab / initial-focus / restore-on-close / Escape-to-close /
 * body-scroll-lock recipe every modal in this app should run. Originally
 * inlined inside the ``Dialog`` primitive; extracted so other modal-like
 * surfaces (CommandPalette, ShortcutOverlay, future custom overlays) can
 * share it without duplicating ~40 lines of nuanced focus code.
 *
 * Pass the dialog's panel element via ``panelRef``; the hook focuses the
 * first focusable child on open (falling back to the panel itself if there
 * are none), restores focus to whatever was active before opening on close,
 * cycles Tab inside the panel while open, closes on Escape, and toggles
 * ``body.style.overflow = hidden`` so background content can't be scrolled
 * behind a modal.
 *
 * Setup is keyed strictly on ``open`` — NOT on the caller's ``onClose``
 * identity. Callers routinely pass an inline ``onClose`` (e.g. ``() => {
 * setOpen(false); resetForm(); }``) that changes every render; the previous
 * version listed the derived key handler in this effect's deps, so it tore
 * down and re-ran on every keystroke, and the teardown's
 * ``previousFocus.focus()`` yanked focus out of whatever input the user was
 * typing in — letting them enter only one character at a time. The latest
 * ``onClose`` is now read through a ref so the keydown listener stays stable.
 *
 * Best-effort everywhere: guards against unmounted previous-focus nodes and
 * panels without any focusable children. Safe to call on every render —
 * the heavy work is gated by ``open``.
 */
export function useDialogFocus({
  open,
  panelRef,
  onClose,
}: {
  open: boolean;
  panelRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}): void {
  // Hold the latest onClose without making it a listener dependency, so the
  // keydown effect below doesn't re-subscribe (and steal focus) every render.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Trap Tab + Escape-to-close + scroll-lock + restore-focus. Runs once per
  // open/close transition, never per render.
  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !panelRef.current) return;
      const focusables =
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      if (focusables.length === 0) {
        e.preventDefault();
        panelRef.current.focus();
        return;
      }
      const first = focusables[0]!;
      const last = focusables[focusables.length - 1]!;
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && (active === first || active === panelRef.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
      if (previousFocus && previousFocus.isConnected) {
        try {
          previousFocus.focus();
        } catch {
          // ignore — focus restoration is best-effort
        }
      }
    };
  }, [open, panelRef]);

  // Initial focus: prefer the first focusable child so keyboard users can
  // immediately Tab forward; fall back to the panel itself. Once per open.
  useEffect(() => {
    if (!open || !panelRef.current) return;
    const first = panelRef.current.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    (first ?? panelRef.current).focus();
  }, [open, panelRef]);
}
