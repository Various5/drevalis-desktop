import { useState } from 'react';
import { Camera, RotateCcw, Trash2 } from 'lucide-react';
import { type EditorSnapshot } from '@/lib/editor/persistence';

/** Snapshots panel (Phase 2, PR 9b). Named restore points of the whole
 *  timeline, kept in local storage per editor scope. Create one, restore it
 *  (loads it as the current timeline — itself undoable), or delete it. */

function fmtWhen(ms: number): string {
  return new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function SnapshotsPanel({
  snapshots,
  onCreate,
  onRestore,
  onRemove,
}: {
  snapshots: EditorSnapshot[];
  onCreate: (name: string) => void;
  onRestore: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const [name, setName] = useState('');

  const create = () => {
    onCreate(name);
    setName('');
  };

  return (
    <div>
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border/60">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') create();
          }}
          placeholder="Snapshot name…"
          className="flex-1 bg-transparent text-xs text-txt-primary placeholder:text-txt-tertiary outline-none border-b border-transparent focus:border-border px-1"
        />
        <button
          onClick={create}
          className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-bg-elevated text-txt-secondary hover:text-txt-primary"
          title="Take snapshot"
        >
          <Camera size={12} />
          Add
        </button>
      </div>

      {snapshots.length === 0 ? (
        <p className="text-xs text-txt-tertiary px-2 py-3">No snapshots yet.</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {snapshots.map((s) => (
            <li key={s.id} className="flex items-center gap-2 px-2 py-1.5">
              <button
                onClick={() => onRestore(s.id)}
                className="flex items-center gap-1.5 text-emerald-400 hover:text-emerald-300 shrink-0"
                title="Restore this snapshot"
              >
                <RotateCcw size={12} />
              </button>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-txt-primary truncate">{s.name}</div>
                <div className="text-[10px] text-txt-tertiary tabular-nums">{fmtWhen(s.createdAt)}</div>
              </div>
              <button onClick={() => onRemove(s.id)} className="text-txt-tertiary hover:text-error shrink-0" aria-label="Delete snapshot">
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
