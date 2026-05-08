import { useState } from 'react';
import { AssetPicker } from '@/components/assets/AssetPicker';

// Small helper that renders selected asset thumbnails + a "Pick
// assets" button. ``ids`` is the comma-separated string the save
// payload already uses, so plugging this in didn't require the
// parent to track an array separately.

export function AssetLockPicker({
  ids,
  onChange,
  title,
}: {
  ids: string;
  onChange: (next: string) => void;
  title: string;
}) {
  const parsed = ids
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-2">
      {parsed.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {parsed.map((id) => (
            <div
              key={id}
              className="relative w-14 h-14 rounded border border-white/[0.06] overflow-hidden group"
              title={id}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/api/v1/assets/${id}/file`}
                alt=""
                className="w-full h-full object-cover"
              />
              <button
                onClick={() => {
                  const next = parsed.filter((x) => x !== id).join(', ');
                  onChange(next);
                }}
                className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 flex items-center justify-center text-white text-[10px] transition-opacity"
                title="Remove"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-txt-muted">
          No reference assets selected.
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs text-accent hover:underline"
      >
        {parsed.length > 0
          ? 'Change reference assets…'
          : 'Pick reference assets…'}
      </button>
      {open && (
        <AssetPicker
          open
          onClose={() => setOpen(false)}
          onSelect={(next) => onChange(next.join(', '))}
          kind="image"
          initialSelectedIds={parsed}
          title={title}
        />
      )}
    </div>
  );
}
