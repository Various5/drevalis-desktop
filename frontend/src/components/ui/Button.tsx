import { forwardRef, type ButtonHTMLAttributes } from 'react';

// ---------------------------------------------------------------------------
// Variants & Sizes
// ---------------------------------------------------------------------------

const variantClasses = {
  primary:
    'bg-gradient-to-r from-accent to-[#00BFA8] text-[#021F18] font-semibold shadow-sm hover:shadow-accent-glow hover:brightness-110 hover:scale-[1.02] active:scale-[0.98] active:brightness-95',
  secondary:
    'bg-bg-elevated/80 text-txt-primary border border-white/[0.06] hover:bg-bg-hover hover:border-white/[0.1] active:bg-bg-active backdrop-blur-sm hover:scale-[1.01] active:scale-[0.99]',
  ghost:
    'text-txt-secondary hover:text-txt-primary hover:bg-bg-hover/60 active:bg-bg-active/60',
  destructive:
    'bg-error/10 text-error border border-error/20 hover:bg-error/15 hover:border-error/30 active:bg-error/20',
} as const;

const sizeClasses = {
  sm: 'h-9 md:h-7 px-2.5 text-xs gap-1 rounded-sm',  // 44px mobile, 28px desktop
  md: 'h-10 md:h-8 px-3 text-sm gap-1.5 rounded',     // 44px mobile, 32px desktop
  lg: 'h-11 md:h-10 px-4 text-base gap-2 rounded-md',  // 44px mobile, 40px desktop
} as const;

type Variant = keyof typeof variantClasses;
type Size = keyof typeof sizeClasses;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      disabled,
      className = '',
      children,
      ...props
    },
    ref,
  ) => {
    const isDisabled = disabled || loading;

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={[
          'inline-flex items-center justify-center font-display font-medium transition-all duration-200 whitespace-nowrap select-none',
          'focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2',
          'disabled:opacity-50 disabled:pointer-events-none',
          variantClasses[variant],
          sizeClasses[size],
          className,
        ].join(' ')}
        {...props}
      >
        {loading && (
          <svg
            className="animate-spin h-3 w-3 shrink-0"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="2.5"
              className="opacity-[0.15]"
            />
            <path
              d="M12 2a10 10 0 019.95 9"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              className="opacity-90"
            />
          </svg>
        )}
        {children}
      </button>
    );
  },
);

Button.displayName = 'Button';

export { Button };
export type { ButtonProps, Variant as ButtonVariant, Size as ButtonSize };
