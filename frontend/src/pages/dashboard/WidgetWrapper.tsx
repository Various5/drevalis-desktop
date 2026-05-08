import { useRef, type ReactNode } from 'react';
import { GripVertical, EyeOff } from 'lucide-react';
import type { WidgetId } from './types';

// =============================================================================
// WidgetWrapper — drag handle + hide overlay for edit mode.
//
// Native HTML5 drag-and-drop only. No extra library.
// Below md: drag-and-drop is disabled (touch is unreliable with HTML5 dnd).
// =============================================================================

interface WidgetWrapperProps {
  id: WidgetId;
  index: number;
  editMode: boolean;
  isDragTarget: boolean;
  onHide: (id: WidgetId) => void;
  onDragStart: (index: number) => void;
  onDragOver: (e: React.DragEvent, index: number) => void;
  onDrop: (index: number) => void;
  onDragEnd: () => void;
  children: ReactNode;
}

export function WidgetWrapper({
  id,
  index,
  editMode,
  isDragTarget,
  onHide,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  children,
}: WidgetWrapperProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);

  if (!editMode) {
    // Outside edit mode: render with a stable key (provided by parent via key prop)
    // so React doesn't remount the widget body on reorder.
    return <div data-widget-id={id}>{children}</div>;
  }

  return (
    <div
      ref={wrapperRef}
      data-widget-id={id}
      // Only enable dragging on md+ via the draggable attribute being
      // conditional on pointer type is not possible in HTML; instead we
      // hide the grip handle below md and still set draggable=true but
      // the visual affordance is absent on small screens.
      draggable
      onDragStart={() => onDragStart(index)}
      onDragOver={(e) => {
        e.preventDefault();
        onDragOver(e, index);
      }}
      onDrop={(e) => {
        e.preventDefault();
        onDrop(index);
      }}
      onDragEnd={onDragEnd}
      className={[
        'relative group',
        'rounded-xl',
        'ring-1',
        isDragTarget
          ? 'ring-accent/60 bg-accent/[0.03]'
          : 'ring-white/[0.06]',
        'transition-all duration-150',
      ].join(' ')}
      aria-label={`Widget: ${id}, draggable`}
    >
      {/* Drag handle — hidden below md (touch users use the dialog instead) */}
      <button
        type="button"
        className="hidden md:flex absolute left-2 top-2 z-10 p-1 rounded text-txt-tertiary hover:text-txt-primary hover:bg-bg-hover/60 transition-colors cursor-grab active:cursor-grabbing"
        aria-label={`Drag to reorder widget: ${id}`}
        // The button itself doesn't initiate drag — the wrapper div does.
        // Clicking it would bubble to the wrapper's dragstart which only
        // fires on pointer-drag. This button is purely a visual affordance.
        tabIndex={0}
      >
        <GripVertical size={14} />
      </button>

      {/* Hide button */}
      <button
        type="button"
        onClick={() => onHide(id)}
        className="absolute right-2 top-2 z-10 p-1 rounded text-txt-tertiary hover:text-error hover:bg-error/10 transition-colors"
        aria-label={`Hide widget: ${id}`}
        tabIndex={0}
      >
        <EyeOff size={14} />
      </button>

      {/* Widget content — pointer-events-none while dragging so the
          overlay captures the drop events correctly. */}
      <div className="pointer-events-none select-none">{children}</div>
    </div>
  );
}
