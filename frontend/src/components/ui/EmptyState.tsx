import { type ReactNode, type HTMLAttributes, type ElementType } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Accept any component-like that takes a size and className. We use
// ElementType (rather than ComponentType<{...}>) because lucide-react
// exports its icons as ForwardRefExoticComponent, whose propTypes are
// incompatible with a narrowly-typed ComponentType — TS rejects the
// assignment even though every lucide icon does in fact accept
// `size` and `className` at runtime.
type IconLike = ElementType;

interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /**
   * Lucide-react (or any compatible) icon component.
   * Rendered at 48px. Receives `size` and `className` props.
   */
  icon?: IconLike;
  /** Primary heading — required (string or richer ReactNode). */
  title: ReactNode;
  /** Supporting copy — optional, capped at max-w-xs */
  description?: ReactNode;
  /** Call-to-action slot — pass a <Button> or any ReactNode */
  action?: ReactNode;
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className = '',
  ...props
}: EmptyStateProps) {
  return (
    <div
      role="status"
      className={[
        'flex flex-col items-center justify-center text-center',
        'py-12 px-6',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...props}
    >
      {Icon && (
        <div
          className="mb-4 flex items-center justify-center"
          aria-hidden="true"
        >
          <Icon size={48} className="text-txt-tertiary" />
        </div>
      )}

      <h3 className="text-xl font-display font-semibold text-txt-primary leading-snug">
        {title}
      </h3>

      {description && (
        <p className="mt-2 text-md font-display text-txt-secondary max-w-xs leading-relaxed">
          {description}
        </p>
      )}

      {action && (
        <div className="mt-6">
          {action}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { EmptyState };
export type { EmptyStateProps };
