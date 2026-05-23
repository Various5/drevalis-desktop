/** History panel (Phase 2, PR 9). Lists the undo/redo revision stack newest
 *  first; the current revision is highlighted and revisions ahead of it (redo
 *  range) are dimmed. Click any entry to jump straight to it — equivalent to
 *  repeated undo/redo, so the stack is preserved until the next edit. */

export function HistoryPanel({
  count,
  index,
  onJump,
}: {
  count: number;
  index: number;
  onJump: (index: number) => void;
}) {
  const items = Array.from({ length: count }, (_, i) => i).reverse();
  return (
    <ul className="max-h-44 overflow-auto">
      {items.map((i) => {
        const current = i === index;
        const future = i > index;
        return (
          <li key={i}>
            <button
              onClick={() => onJump(i)}
              className={`flex items-center gap-2 w-full px-2 py-1 text-xs text-left ${
                current
                  ? 'bg-accent/15 text-accent'
                  : future
                    ? 'text-txt-tertiary hover:text-txt-secondary'
                    : 'text-txt-secondary hover:text-txt-primary'
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${current ? 'bg-accent' : 'bg-txt-tertiary/40'}`} />
              <span className="tabular-nums">{i === 0 ? 'Initial state' : `Edit ${i}`}</span>
              {current && <span className="ml-auto text-[10px] uppercase tracking-wide">current</span>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
