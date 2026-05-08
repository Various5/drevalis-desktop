import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BreadcrumbItem {
  label: string;
  /** If provided, renders as a link. Otherwise renders as plain text (current page). */
  to?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function Breadcrumb({ items, className = '' }: BreadcrumbProps) {
  if (items.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className={className}>
      <ol className="flex items-center gap-1.5 text-sm">
        {items.map((item, index) => {
          const isLast = index === items.length - 1;

          return (
            <li key={index} className="flex items-center gap-1.5">
              {index > 0 && (
                <ChevronRight
                  size={12}
                  className="text-txt-tertiary shrink-0"
                  aria-hidden="true"
                />
              )}

              {item.to && !isLast ? (
                <Link
                  to={item.to}
                  className="font-display text-txt-secondary hover:text-txt-primary transition-colors duration-fast truncate max-w-[200px]"
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  className="font-display text-txt-primary font-medium truncate max-w-[200px]"
                  aria-current={isLast ? 'page' : undefined}
                >
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export { Breadcrumb };
export type { BreadcrumbItem, BreadcrumbProps };
