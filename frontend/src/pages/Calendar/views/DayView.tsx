// ---------------------------------------------------------------------------
// DayView — single-day 24-hour timeline.
// Inspection only in v1. The current-time line renders when the shown date
// is today (handled inside TimelineGrid).
// ---------------------------------------------------------------------------

import { TimelineGrid } from './TimelineGrid';
import type { ScheduledPost } from '../types';

interface DayViewProps {
  date: Date;
  posts: ScheduledPost[];
  onCancel: (id: string) => void;
}

export function DayView({ date, posts, onCancel }: DayViewProps) {
  return (
    <div className="flex flex-col h-full" data-testid="day-view">
      <TimelineGrid columns={[date]} posts={posts} onCancel={onCancel} />
    </div>
  );
}
