import type { ReactNode } from 'react';
import { Card } from '@/components/ui/Card';

// StatCard — labelled metric tile used on Dashboard, Usage, Logs,
// YouTube, etc. Was copy-pasted across pages with subtle drift in
// padding, label casing, and icon treatment. This component is the
// single source of truth.

interface StatCardProps {
  label: string;
  value: ReactNode;
  /** Optional secondary line below the value (e.g. a delta or breakdown). */
  sub?: ReactNode;
  /** Lucide icon node — pass `<Icon size={20} />` etc. Optional. */
  icon?: ReactNode;
  /**
   * CSS color string for the icon tint (background + foreground). When
   * unspecified the icon inherits the accent color. The Dashboard
   * uses semantic per-stat hues (success/warning/error), so this is
   * an arbitrary string instead of a variant key.
   */
  color?: string;
  className?: string;
}

export function StatCard({
  label,
  value,
  sub,
  icon,
  color,
  className = '',
}: StatCardProps) {
  return (
    <Card padding="md" className={`edge-highlight ${className}`}>
      <div className="flex items-center gap-4">
        {icon && (
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0 icon-hover"
            style={
              color
                ? { backgroundColor: `${color}12`, color }
                : undefined
            }
          >
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <p className="text-2xl font-display font-bold text-txt-primary tracking-tight truncate">
            {value}
          </p>
          <p className="text-xs font-display font-medium text-txt-tertiary tracking-wide uppercase">
            {label}
          </p>
          {sub && (
            <p className="text-[11px] text-txt-muted mt-0.5">{sub}</p>
          )}
        </div>
      </div>
    </Card>
  );
}

export default StatCard;
