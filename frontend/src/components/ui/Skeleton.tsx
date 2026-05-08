import { type HTMLAttributes } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type RoundedVariant = 'sm' | 'md' | 'lg' | 'full';

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Additional Tailwind classes or custom classes */
  className?: string;
  /** Explicit width — accepts any valid CSS value e.g. "120px", "100%", "8rem" */
  width?: string;
  /** Explicit height — accepts any valid CSS value e.g. "16px", "1rem" */
  height?: string;
  /** Border radius preset */
  rounded?: RoundedVariant;
}

// ---------------------------------------------------------------------------
// Border radius map
// ---------------------------------------------------------------------------

const roundedClasses: Record<RoundedVariant, string> = {
  sm:   'rounded-sm',  // 4px
  md:   'rounded-md',  // 8px
  lg:   'rounded-lg',  // 10px
  full: 'rounded-full',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function Skeleton({
  className = '',
  width,
  height,
  rounded = 'md',
  style,
  ...props
}: SkeletonProps) {
  return (
    <>
      {/*
        The shimmer keyframe is defined inline via a <style> tag so this
        component is fully self-contained without requiring a globals.css edit.
        The @media prefers-reduced-motion block replaces the moving gradient
        with a simple static pulse, keeping the element visible but calm.
      */}
      <style>{`
        @keyframes skeleton-shimmer {
          0%   { background-position: 200% center; }
          100% { background-position: -200% center; }
        }
        .skeleton-shimmer {
          background: linear-gradient(
            90deg,
            #1A1A1E 0%,
            #2A2A32 50%,
            #1A1A1E 100%
          );
          background-size: 200% 100%;
          animation: skeleton-shimmer 1.5s ease-in-out infinite;
        }
        @media (prefers-reduced-motion: reduce) {
          .skeleton-shimmer {
            animation: none;
            background: #1A1A1E;
            opacity: 0.8;
          }
        }
      `}</style>

      <div
        role="status"
        aria-label="Loading"
        aria-busy="true"
        className={[
          'skeleton-shimmer',
          roundedClasses[rounded],
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        style={{ width, height, ...style }}
        {...props}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Convenience compositions
// ---------------------------------------------------------------------------

/** A full-width single-line text skeleton. Height defaults to 1rem (16px). */
function SkeletonText({
  className = '',
  lines = 1,
  lastLineWidth = '75%',
}: {
  className?: string;
  lines?: number;
  /** Width of the last line — simulates ragged text edge */
  lastLineWidth?: string;
}) {
  return (
    <div className={`flex flex-col gap-2 ${className}`} aria-busy="true" role="status" aria-label="Loading text">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height="0.875rem"
          width={i === lines - 1 && lines > 1 ? lastLineWidth : '100%'}
          rounded="sm"
        />
      ))}
    </div>
  );
}

/** A square or rectangular block — useful for image/thumbnail placeholders. */
function SkeletonBlock({
  width = '100%',
  height = '8rem',
  rounded = 'md',
  className = '',
}: {
  width?: string;
  height?: string;
  rounded?: RoundedVariant;
  className?: string;
}) {
  return <Skeleton width={width} height={height} rounded={rounded} className={className} />;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Skeleton, SkeletonText, SkeletonBlock };
export type { SkeletonProps, RoundedVariant };
