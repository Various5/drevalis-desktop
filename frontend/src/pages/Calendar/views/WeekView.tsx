// ---------------------------------------------------------------------------
// WeekView — 7-column 24-hour timeline (Mon → Sun).
// Inspection only in v1; drag-and-drop is month-view only per spec.
// ---------------------------------------------------------------------------

import { TimelineGrid } from './TimelineGrid';
import type { ScheduledPost } from '../types';

interface WeekViewProps {
  /** The Monday of the week being shown. */
  weekStart: Date;
  posts: ScheduledPost[];
  onCancel: (id: string) => void;
}

/** Returns the 7 dates (Mon–Sun) of the week starting at weekStart. */
function getWeekDays(weekStart: Date): Date[] {
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    return d;
  });
}

export function WeekView({ weekStart, posts, onCancel }: WeekViewProps) {
  const columns = getWeekDays(weekStart);

  return (
    <div className="flex flex-col h-full" data-testid="week-view">
      <TimelineGrid columns={columns} posts={posts} onCancel={onCancel} />
    </div>
  );
}
