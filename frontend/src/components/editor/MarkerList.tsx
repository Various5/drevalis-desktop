import { useEffect, useState } from 'react';
import { Flag, Trash2 } from 'lucide-react';
import { type Marker } from '@/lib/editor/timeline';

/** Marker list panel (Phase 2, PR 5b). Click a marker to seek, edit its note
 *  inline (committed on blur so it's one undo entry), or delete it. */

function fmt(frame: number, fps: number): string {
  const totalSec = frame / fps;
  const m = Math.floor(totalSec / 60);
  const s = (totalSec % 60).toFixed(1);
  return `${m}:${s.padStart(4, '0')}`;
}

function MarkerRow({
  marker,
  fps,
  onSeek,
  onRemove,
  onEditNote,
}: {
  marker: Marker;
  fps: number;
  onSeek: (frame: number) => void;
  onRemove: (id: string) => void;
  onEditNote: (id: string, note: string) => void;
}) {
  const [note, setNote] = useState(marker.note ?? '');
  // Resync if the note changes externally (e.g. undo/redo).
  useEffect(() => setNote(marker.note ?? ''), [marker.note]);

  return (
    <li className="flex items-center gap-2 px-2 py-1.5">
      <button
        onClick={() => onSeek(marker.frame)}
        className="flex items-center gap-1.5 text-amber-400 hover:text-amber-300 shrink-0 tabular-nums text-xs"
        title="Seek to marker"
      >
        <Flag size={12} />
        {fmt(marker.frame, fps)}
      </button>
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onBlur={() => {
          if (note !== (marker.note ?? '')) onEditNote(marker.id, note);
        }}
        placeholder="Note…"
        className="flex-1 bg-transparent text-xs text-txt-primary placeholder:text-txt-tertiary outline-none border-b border-transparent focus:border-border px-1"
      />
      <button
        onClick={() => onRemove(marker.id)}
        className="text-txt-tertiary hover:text-error shrink-0"
        aria-label="Delete marker"
      >
        <Trash2 size={13} />
      </button>
    </li>
  );
}

export function MarkerList({
  markers,
  fps,
  onSeek,
  onRemove,
  onEditNote,
}: {
  markers: Marker[];
  fps: number;
  onSeek: (frame: number) => void;
  onRemove: (id: string) => void;
  onEditNote: (id: string, note: string) => void;
}) {
  if (markers.length === 0) {
    return <p className="text-xs text-txt-tertiary px-2 py-3">No markers — press M at the playhead to add one.</p>;
  }
  return (
    <ul className="divide-y divide-border/60">
      {markers.map((m) => (
        <MarkerRow key={m.id} marker={m} fps={fps} onSeek={onSeek} onRemove={onRemove} onEditNote={onEditNote} />
      ))}
    </ul>
  );
}
