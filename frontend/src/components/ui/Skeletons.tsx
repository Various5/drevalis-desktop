import { Skeleton } from './Skeleton';

/**
 * Composite loading skeletons (Phase 3). Content-shaped placeholders that
 * replace centered spinners on async list/grid routes, so a loading screen
 * reads as "about to fill in" rather than "blank/broken". Pass the page's own
 * grid classes so the skeleton matches the real layout.
 */

export function CardGridSkeleton({
  count = 6,
  gridClassName = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4',
  square = false,
}: {
  count?: number;
  /** The same grid classes the real list uses, so the skeleton lines up. */
  gridClassName?: string;
  /** Square thumbnails (asset tiles) vs 16:9 (episode/series cards). */
  square?: boolean;
}) {
  return (
    <div className={gridClassName} aria-hidden>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-border bg-bg-surface p-3 space-y-3">
          <Skeleton className={`w-full ${square ? 'aspect-square' : 'aspect-video'}`} rounded="md" />
          <Skeleton className="h-3 w-3/4" rounded="sm" />
          <Skeleton className="h-3 w-1/2" rounded="sm" />
        </div>
      ))}
    </div>
  );
}

export function ListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 rounded-lg border border-border bg-bg-surface p-3">
          <Skeleton className="h-10 w-10 shrink-0" rounded="md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3 w-2/5" rounded="sm" />
            <Skeleton className="h-3 w-3/5" rounded="sm" />
          </div>
          <Skeleton className="h-5 w-16 shrink-0" rounded="full" />
        </div>
      ))}
    </div>
  );
}
