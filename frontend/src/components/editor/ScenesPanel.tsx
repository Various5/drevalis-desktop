import { useEffect, useState } from 'react';
import { Clapperboard, Plus, Trash2 } from 'lucide-react';
import { type Scene } from '@/lib/editor/timeline';

/** Scenes panel (Phase 2, PR 7). Lists named chapters/segments in time order;
 *  rename inline (committed on blur), click the time to seek, add a scene at
 *  the playhead, or delete one. */

function fmt(frame: number, fps: number): string {
  const totalSec = frame / fps;
  const m = Math.floor(totalSec / 60);
  const s = (totalSec % 60).toFixed(1);
  return `${m}:${s.padStart(4, '0')}`;
}

function SceneRow({
  scene,
  index,
  fps,
  onSeek,
  onRename,
  onRemove,
}: {
  scene: Scene;
  index: number;
  fps: number;
  onSeek: (frame: number) => void;
  onRename: (id: string, name: string) => void;
  onRemove: (id: string) => void;
}) {
  const [name, setName] = useState(scene.name);
  useEffect(() => setName(scene.name), [scene.name]);

  return (
    <li className="flex items-center gap-2 px-2 py-1.5">
      <button
        onClick={() => onSeek(scene.startFrame)}
        className="flex items-center gap-1.5 text-violet-400 hover:text-violet-300 shrink-0 tabular-nums text-xs"
        title="Seek to scene"
      >
        <span className="text-txt-tertiary">{index + 1}.</span>
        {fmt(scene.startFrame, fps)}
      </button>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => {
          if (name !== scene.name) onRename(scene.id, name);
        }}
        placeholder="Scene name…"
        className="flex-1 bg-transparent text-xs text-txt-primary placeholder:text-txt-tertiary outline-none border-b border-transparent focus:border-border px-1"
      />
      <button onClick={() => onRemove(scene.id)} className="text-txt-tertiary hover:text-error shrink-0" aria-label="Delete scene">
        <Trash2 size={13} />
      </button>
    </li>
  );
}

export function ScenesPanel({
  scenes,
  fps,
  onSeek,
  onRename,
  onRemove,
  onAdd,
}: {
  scenes: Scene[];
  fps: number;
  onSeek: (frame: number) => void;
  onRename: (id: string, name: string) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
}) {
  return (
    <div>
      {scenes.length === 0 ? (
        <p className="text-xs text-txt-tertiary px-2 py-3">No scenes yet.</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {scenes.map((s, i) => (
            <SceneRow key={s.id} scene={s} index={i} fps={fps} onSeek={onSeek} onRename={onRename} onRemove={onRemove} />
          ))}
        </ul>
      )}
      <button
        onClick={onAdd}
        className="flex items-center gap-1.5 w-full px-2 py-1.5 text-xs text-txt-secondary hover:text-txt-primary border-t border-border/60"
      >
        <Clapperboard size={13} />
        <Plus size={12} />
        Add scene at playhead
      </button>
    </div>
  );
}
