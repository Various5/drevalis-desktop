import { forwardRef, type HTMLAttributes } from 'react';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
  selected?: boolean;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const paddingClasses = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
} as const;

const Card = forwardRef<HTMLDivElement, CardProps>(
  (
    {
      interactive = false,
      selected = false,
      padding = 'md',
      className = '',
      children,
      onClick,
      onKeyDown,
      ...props
    },
    ref,
  ) => {
    const handleKeyDown = interactive
      ? (e: React.KeyboardEvent<HTMLDivElement>) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            (e.currentTarget as HTMLDivElement).click();
          }
          onKeyDown?.(e);
        }
      : onKeyDown;

    return (
      <div
        ref={ref}
        role={interactive ? 'button' : undefined}
        tabIndex={interactive ? 0 : undefined}
        className={[
          interactive
            ? 'bg-bg-surface/80 backdrop-blur-sm border border-white/[0.06] rounded-xl cursor-pointer card-lift edge-highlight hover:bg-bg-surface/90 hover:border-white/[0.1]'
            : 'bg-bg-surface/80 backdrop-blur-sm border border-white/[0.06] rounded-xl',
          selected && 'border-accent/40 shadow-accent-glow',
          paddingClasses[padding],
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        onClick={onClick}
        onKeyDown={handleKeyDown}
        {...props}
      >
        {children}
      </div>
    );
  },
);

Card.displayName = 'Card';

// ---------------------------------------------------------------------------
// Card sub-components
// ---------------------------------------------------------------------------

function CardHeader({
  className = '',
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`flex items-center justify-between gap-3 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

function CardTitle({
  className = '',
  children,
  ...props
}: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={`text-md font-semibold text-txt-primary ${className}`} {...props}>
      {children}
    </h3>
  );
}

function CardDescription({
  className = '',
  children,
  ...props
}: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={`text-sm text-txt-secondary text-clamp-2 ${className}`} {...props}>
      {children}
    </p>
  );
}

function CardContent({
  className = '',
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`mt-3 ${className}`} {...props}>
      {children}
    </div>
  );
}

function CardFooter({
  className = '',
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`mt-3 pt-3 border-t border-border flex items-center gap-2 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter };
export type { CardProps };
