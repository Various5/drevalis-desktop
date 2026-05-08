import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PaginationProps {
  /** Current page (1-based) */
  page: number;
  /** Total number of pages */
  totalPages: number;
  /** Called when the user selects a new page */
  onPageChange: (page: number) => void;
  /** Number of page buttons visible around the current page. Default: 2 */
  siblingCount?: number;
  className?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function range(start: number, end: number): number[] {
  return Array.from({ length: end - start + 1 }, (_, i) => start + i);
}

function getPageNumbers(current: number, total: number, siblings: number): (number | '...')[] {
  const totalSlots = siblings * 2 + 5; // siblings + boundaries + dots + current

  if (total <= totalSlots) return range(1, total);

  const leftSibling = Math.max(current - siblings, 1);
  const rightSibling = Math.min(current + siblings, total);
  const showLeftDots = leftSibling > 3;
  const showRightDots = rightSibling < total - 2;

  if (!showLeftDots && showRightDots) {
    const leftCount = siblings * 2 + 3;
    return [...range(1, leftCount), '...', total];
  }
  if (showLeftDots && !showRightDots) {
    const rightCount = siblings * 2 + 3;
    return [1, '...', ...range(total - rightCount + 1, total)];
  }
  return [1, '...', ...range(leftSibling, rightSibling), '...', total];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function Pagination({
  page,
  totalPages,
  onPageChange,
  siblingCount = 2,
  className = '',
}: PaginationProps) {
  if (totalPages <= 1) return null;

  const pages = getPageNumbers(page, totalPages, siblingCount);

  const btnBase = [
    'inline-flex items-center justify-center',
    'min-w-[32px] h-8 px-1.5 rounded-md text-sm',
    'transition-colors duration-fast',
    'focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1',
    'min-h-[44px] md:min-h-[32px]', // touch target
  ].join(' ');

  const navBtn = [
    btnBase,
    'text-txt-secondary hover:text-txt-primary hover:bg-bg-hover',
    'disabled:text-txt-tertiary disabled:cursor-not-allowed disabled:hover:bg-transparent',
  ].join(' ');

  return (
    <nav
      role="navigation"
      aria-label="Pagination"
      className={`flex items-center justify-center gap-1 ${className}`}
    >
      {/* First */}
      <button
        className={navBtn}
        onClick={() => onPageChange(1)}
        disabled={page === 1}
        aria-label="First page"
      >
        <ChevronsLeft size={16} />
      </button>

      {/* Prev */}
      <button
        className={navBtn}
        onClick={() => onPageChange(page - 1)}
        disabled={page === 1}
        aria-label="Previous page"
      >
        <ChevronLeft size={16} />
      </button>

      {/* Page buttons */}
      {pages.map((p, i) =>
        p === '...' ? (
          <span
            key={`dots-${i}`}
            className="inline-flex items-center justify-center min-w-[32px] h-8 text-sm text-txt-tertiary"
          >
            ...
          </span>
        ) : (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            aria-current={p === page ? 'page' : undefined}
            className={[
              btnBase,
              p === page
                ? 'bg-accent/15 text-accent font-medium'
                : 'text-txt-secondary hover:text-txt-primary hover:bg-bg-hover',
            ].join(' ')}
          >
            {p}
          </button>
        ),
      )}

      {/* Next */}
      <button
        className={navBtn}
        onClick={() => onPageChange(page + 1)}
        disabled={page === totalPages}
        aria-label="Next page"
      >
        <ChevronRight size={16} />
      </button>

      {/* Last */}
      <button
        className={navBtn}
        onClick={() => onPageChange(totalPages)}
        disabled={page === totalPages}
        aria-label="Last page"
      >
        <ChevronsRight size={16} />
      </button>
    </nav>
  );
}

export { Pagination };
export type { PaginationProps };
