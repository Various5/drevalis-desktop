import { useEffect, useState } from 'react';
import { Captions, Plus, Trash2 } from 'lucide-react';

/** Captions panel (Phase 2, PR 7). Lists caption clips in time order; edit text
 *  inline (committed on blur so it's one undo entry), click the time to seek,
 *  add a caption at the playhead, or delete one. */

export interface CaptionEntry {
  id: string;
  startFrame: number;
  text: string;
}

function fmt(frame: number, fps: number): string {
  const totalSec = frame / fps;
  const m = Math.floor(totalSec / 60);
  const s = (totalSec % 60).toFixed(1);
  return `${m}:${s.padStart(4, '0')}`;
}

function CaptionRow({
  caption,
  fps,
  onSeek,
  onEdit,
  onRemove,
}: {
  caption: CaptionEntry;
  fps: number;
  onSeek: (frame: number) => void;
  onEdit: (id: string, text: string) => void;
  onRemove: (id: string) => void;
}) {
  const [text, setText] = useState(caption.text);
  useEffect(() => setText(caption.text), [caption.text]);

  return (
    <li className="flex items-center gap-2 px-2 py-1.5">
      <button
        onClick={() => onSeek(caption.startFrame)}
        className="text-sky-400 hover:text-sky-300 shrink-0 tabular-nums text-xs"
        title="Seek to caption"
      >
        {fmt(caption.startFrame, fps)}
      </button>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if (text !== caption.text) onEdit(caption.id, text);
        }}
        placeholder="Caption text…"
        className="flex-1 bg-transparent text-xs text-txt-primary placeholder:text-txt-tertiary outline-none border-b border-transparent focus:border-border px-1"
      />
      <button onClick={() => onRemove(caption.id)} className="text-txt-tertiary hover:text-error shrink-0" aria-label="Delete caption">
        <Trash2 size={13} />
      </button>
    </li>
  );
}

export function CaptionsPanel({
  captions,
  fps,
  onSeek,
  onEdit,
  onRemove,
  onAdd,
}: {
  captions: CaptionEntry[];
  fps: number;
  onSeek: (frame: number) => void;
  onEdit: (id: string, text: string) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
}) {
  return (
    <div>
      {captions.length === 0 ? (
        <p className="text-xs text-txt-tertiary px-2 py-3">No captions yet.</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {captions.map((c) => (
            <CaptionRow key={c.id} caption={c} fps={fps} onSeek={onSeek} onEdit={onEdit} onRemove={onRemove} />
          ))}
        </ul>
      )}
      <button
        onClick={onAdd}
        className="flex items-center gap-1.5 w-full px-2 py-1.5 text-xs text-txt-secondary hover:text-txt-primary border-t border-border/60"
      >
        <Captions size={13} />
        <Plus size={12} />
        Add caption at playhead
      </button>
    </div>
  );
}
