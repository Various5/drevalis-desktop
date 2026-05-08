import type { ReactNode } from 'react';

// PageHeader — single in-page header used at the top of every page.
//
// The fixed top banner (``layout/Header.tsx``) already shows the page
// title, so each page used to render its own duplicate ``<h1>`` plus a
// subtitle plus actions in inconsistent layouts. This component
// standardizes that "subtitle + actions" row.
//
// Pass ``title`` only when the page legitimately needs to repeat the
// title (e.g. a section page nested inside a parent route, or pages
// where the banner doesn't reflect the entity name yet). Otherwise
// leave it undefined and the layout falls back to subtitle-only.

interface PageHeaderProps {
  title?: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({
  title,
  subtitle,
  actions,
  className = '',
}: PageHeaderProps) {
  return (
    <header
      className={[
        'flex items-start justify-between gap-4 flex-wrap mb-5',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="min-w-0 flex-1">
        {title && (
          <h1 className="text-xl font-display font-semibold text-txt-primary tracking-tight">
            {title}
          </h1>
        )}
        {subtitle && (
          <div className="text-sm text-txt-secondary mt-1">{subtitle}</div>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </header>
  );
}

export default PageHeader;
