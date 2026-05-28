import { useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useDialogFocus } from '@/lib/useDialogFocus';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl';
}

// ---------------------------------------------------------------------------
// Width map
// ---------------------------------------------------------------------------
//
// The previous map (sm=24rem, md=28rem, lg=32rem, xl=36rem) was too
// tight for dialogs with multi-step content (the OAuth setup wizard
// in particular). On 125-150% Windows scaling those caps left the
// action footer pushed below the viewport. Bumped lg/xl while
// keeping sm/md unchanged for confirmation dialogs.

const maxWidthClasses = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-3xl',
} as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  className = '',
  maxWidth = 'md',
}: DialogProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Trap Tab inside the panel, restore focus on close, lock body scroll,
  // and close on Escape — shared with CommandPalette / ShortcutOverlay /
  // any future custom modal via the same hook.
  useDialogFocus({ open, panelRef, onClose });

  if (!open) return null;

  // Render via portal directly into document.body so the dialog
  // escapes every layout stacking context. Otherwise ancestors that
  // create a containing block for ``position: fixed`` (Sidebar +
  // Header both use ``backdrop-blur-xl``, which promotes them via
  // the backdrop-filter property) trap the overlay inside the page
  // area and let themselves render *on top* of the dialog — visible
  // as a "blurred bar at the edges" plus action buttons that look
  // clickable but actually sit behind the sidebar/header layer.
  if (typeof document === 'undefined') return null;

  const dialog = (
    <div className="fixed inset-0 z-modal flex items-center justify-center p-4">
      {/* Backdrop — solid-ish overlay (no backdrop-filter) so the
          content underneath isn't smeared into the dialog body
          through the panel's translucent surface. The previous
          ``bg-bg-overlay`` token plus the panel's own
          ``backdrop-blur-xl`` produced the "blurred bar around the
          edges" effect users were seeing. */}
      <div
        ref={overlayRef}
        className="absolute inset-0 bg-black/60 animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel — height-capped so dialogs that overflow on small or
          high-DPI viewports become scrollable instead of pushing the
          action footer below the visible window. The panel is a flex
          column: header + scroll body + (sticky footer if a
          DialogFooter is rendered inside ``children``). */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={[
          'relative w-full rounded-xl animate-scale-in flex flex-col',
          'max-h-[calc(100vh-2rem)]',
          // Opaque surface — no backdrop-filter. ``backdrop-blur`` on
          // a position:fixed panel was leaking the page underneath
          // *through* the panel and producing a blurred fringe at
          // the edges; with ``bg-bg-surface`` solid the panel is a
          // clean window over the backdrop.
          'bg-bg-surface border border-white/[0.08]',
          'shadow-glass',
          maxWidthClasses[maxWidth],
          className,
        ].join(' ')}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4 shrink-0">
          <div>
            <h2 className="text-lg font-display font-semibold text-txt-primary">{title}</h2>
            {description && (
              <p className="mt-1 text-sm text-txt-secondary">{description}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 p-1 rounded text-txt-tertiary hover:text-txt-primary hover:bg-bg-hover transition-colors duration-fast"
            aria-label="Close dialog"
          >
            <X size={16} />
          </button>
        </div>

        {/* Scrollable body. ``min-h-0`` is required so the flex child
            actually scrolls instead of growing past the panel cap. A
            DialogFooter rendered inside this scroller uses
            ``position: sticky`` to stay pinned at the bottom edge,
            so action buttons are always reachable. */}
        <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-6">
          {children}
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DialogFooter({
  className = '',
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  // Sticks to the bottom of the dialog's scroll body so the primary
  // action stays reachable no matter how tall the body content is.
  // The negative margins + matching horizontal padding cancel the
  // body's px-6 pb-6 so the footer's tinted background spans the
  // full panel width and rides flush with the bottom rounded corner.
  return (
    <div
      className={[
        'sticky bottom-0 -mx-6 -mb-6 mt-6 px-6 pt-4 pb-6',
        'flex items-center justify-end gap-2 flex-wrap',
        // Opaque so it occludes scrolled content above it. The
        // earlier ``bg-bg-surface/95 backdrop-blur`` showed scrolled
        // content faintly through the footer.
        'bg-bg-surface border-t border-white/[0.06]',
        'rounded-b-xl',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  );
}

export { Dialog, DialogFooter };
export type { DialogProps };
