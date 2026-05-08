import { useId } from 'react';

// ---------------------------------------------------------------------------
// Loading Spinner
// ---------------------------------------------------------------------------

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizeClasses = {
  sm: 'h-4 w-4',
  md: 'h-6 w-6',
  lg: 'h-8 w-8',
} as const;

function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  // Unique gradient id per render so two spinners on the same page don't
  // collide. ``id`` collisions on SVG ``<defs>`` cause the second
  // spinner to inherit the first's gradient — invisible until you hit
  // it on a page like Jobs that mounts several spinners at once.
  const gradientId = `spinner-gradient-${useId()}`;

  return (
    <svg
      className={`animate-spin ${sizeClasses[size]} ${className}`}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="2.5"
        className="opacity-[0.08]"
      />
      <path
        d={`M12 2a10 10 0 019.95 9`}
        stroke={`url(#${gradientId})`}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <defs>
        {/* Gradient stops follow the parent's ``color`` (set via
            ``text-accent`` etc. on the wrapping element), so the spinner
            recolours automatically across theme presets and light mode.
            The second stop fades to half-opacity via ``color-mix``,
            supported in every browser we target (Chrome 111+, Safari
            16.4+, Firefox 113+). */}
        <linearGradient id={gradientId} x1="12" y1="2" x2="22" y2="12">
          <stop stopColor="currentColor" />
          <stop offset="1" stopColor="color-mix(in srgb, currentColor 40%, transparent)" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function FullPageSpinner() {
  return (
    <div className="flex items-center justify-center h-full min-h-[200px]">
      <Spinner size="lg" className="text-accent" />
    </div>
  );
}

export { Spinner, FullPageSpinner };
export type { SpinnerProps };
