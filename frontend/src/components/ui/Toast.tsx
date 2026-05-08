import {
  createContext,
  useCallback,
  useContext,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import * as RadixToast from '@radix-ui/react-toast';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToastVariant = 'success' | 'error' | 'warning' | 'info';

interface ToastItem {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
  /** Duration in ms before auto-dismiss. Defaults based on variant. */
  duration?: number;
}

interface ToastOptions {
  description?: string;
  duration?: number;
}

interface ToastControls {
  success: (title: string, options?: ToastOptions) => void;
  error:   (title: string, options?: ToastOptions) => void;
  warning: (title: string, options?: ToastOptions) => void;
  info:    (title: string, options?: ToastOptions) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ToastContext = createContext<ToastControls | null>(null);

// ---------------------------------------------------------------------------
// Variant config
// ---------------------------------------------------------------------------

const variantConfig: Record<
  ToastVariant,
  { borderColor: string; defaultDuration: number; label: string }
> = {
  success: { borderColor: '#34D399', defaultDuration: 5000, label: 'Success' },
  error:   { borderColor: '#F87171', defaultDuration: 8000, label: 'Error' },
  warning: { borderColor: '#FBBF24', defaultDuration: 8000, label: 'Warning' },
  info:    { borderColor: '#60A5FA', defaultDuration: 5000, label: 'Info' },
};

// ---------------------------------------------------------------------------
// ToastProvider — wraps the app, holds state, exposes imperative API
// ---------------------------------------------------------------------------

// Suppression window: identical (variant, title, description) toasts
// fired within this many ms are dropped. Keeps chained errors from
// stacking five-deep when one underlying failure trips multiple
// retries.
const DEDUP_WINDOW_MS = 2000;

function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // Stable counter for generating unique ids without React re-render cost
  const counter = useRef(0);
  // Recent-toast cache: key → expiry timestamp. We never grow it
  // unboundedly because old entries are cheap to leave (next call to
  // addToast that misses the window simply overwrites the entry).
  const recent = useRef<Map<string, number>>(new Map());

  const addToast = useCallback(
    (variant: ToastVariant, title: string, options?: ToastOptions) => {
      const key = `${variant}|${title}|${options?.description ?? ''}`;
      const now = Date.now();
      const expiry = recent.current.get(key);
      if (expiry !== undefined && expiry > now) {
        return;
      }
      recent.current.set(key, now + DEDUP_WINDOW_MS);

      counter.current += 1;
      const id = `toast-${counter.current}`;
      const { defaultDuration } = variantConfig[variant];
      setToasts((prev) => [
        ...prev,
        {
          id,
          variant,
          title,
          description: options?.description,
          duration: options?.duration ?? defaultDuration,
        },
      ]);
    },
    [],
  );

  const controls: ToastControls = {
    success: (title, opts) => addToast('success', title, opts),
    error:   (title, opts) => addToast('error',   title, opts),
    warning: (title, opts) => addToast('warning', title, opts),
    info:    (title, opts) => addToast('info',    title, opts),
  };

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={controls}>
      <RadixToast.Provider swipeDirection="right">
        {children}

        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}

        {/* Viewport: fixed top-right corner */}
        <RadixToast.Viewport
          className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 outline-none"
          style={{ width: 'min(360px, calc(100vw - 2rem))' }}
          aria-label="Notifications"
        />
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Individual toast item
// ---------------------------------------------------------------------------

interface ToastItemProps {
  toast: ToastItem;
  onDismiss: (id: string) => void;
}

function ToastItem({ toast, onDismiss }: ToastItemProps) {
  const { variant, id, title, description, duration } = toast;
  const { borderColor, label } = variantConfig[variant];
  const labelId = useId();

  return (
    <RadixToast.Root
      duration={duration}
      onOpenChange={(open) => {
        if (!open) onDismiss(id);
      }}
      aria-labelledby={labelId}
      className={[
        // Base surface
        'relative flex items-start gap-3 rounded-md px-4 py-3 shadow-lg',
        'border border-border',
        // Enter animation: slide down + fade in
        'data-[state=open]:animate-slide-down',
        // Exit animation: fade out
        'data-[state=closed]:animate-fade-out',
        // Swipe-to-dismiss gesture
        'data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)]',
        'data-[swipe=cancel]:translate-x-0 data-[swipe=cancel]:transition-transform data-[swipe=cancel]:duration-normal',
        'data-[swipe=end]:animate-fade-out',
        // Reduce motion override
        'motion-reduce:data-[state=open]:animate-none',
        'motion-reduce:data-[state=closed]:animate-none',
      ].join(' ')}
      style={{
        backgroundColor: 'rgba(26, 26, 30, 0.9)',
        backdropFilter: 'blur(20px)',
        borderLeftWidth: '4px',
        borderLeftColor: borderColor,
        borderRadius: '12px',
      }}
    >
      {/* Text content */}
      <div className="flex-1 min-w-0 pt-px">
        <RadixToast.Title
          id={labelId}
          className="text-md font-display font-medium text-txt-primary leading-snug"
        >
          {title}
        </RadixToast.Title>

        {description && (
          <RadixToast.Description className="mt-1 text-sm text-txt-secondary leading-snug">
            {description}
          </RadixToast.Description>
        )}
      </div>

      {/* Close button */}
      <RadixToast.Close
        aria-label={`Dismiss ${label} notification`}
        className={[
          'shrink-0 -mt-0.5 -mr-1 flex items-center justify-center',
          'w-6 h-6 rounded text-txt-tertiary',
          'hover:text-txt-secondary hover:bg-bg-hover',
          'transition-colors duration-fast',
          'focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1',
        ].join(' ')}
      >
        {/* X icon — inline SVG to avoid extra imports */}
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M1 1l10 10M11 1L1 11"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </RadixToast.Close>
    </RadixToast.Root>
  );
}

// ---------------------------------------------------------------------------
// Toaster — place this once inside Layout.tsx (no-op; viewport is in Provider)
// This component exists as a convenience export for layouts that want a
// dedicated import, matching the shadcn/ui convention.
// ---------------------------------------------------------------------------

function Toaster() {
  // The viewport is already rendered inside ToastProvider.
  // This component is intentionally a no-op placeholder for layout clarity.
  return null;
}

// ---------------------------------------------------------------------------
// useToast — imperative hook
// ---------------------------------------------------------------------------

function useToast(): { toast: ToastControls } {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a <ToastProvider>.');
  }
  return { toast: ctx };
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { ToastProvider, Toaster, useToast };
export type { ToastVariant, ToastItem, ToastOptions, ToastControls };
