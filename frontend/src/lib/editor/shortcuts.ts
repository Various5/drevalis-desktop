/**
 * Single source of truth for the editor's keyboard shortcuts (Phase 3, item 7).
 *
 * The cheat-sheet overlay (`KeyboardHelp`) renders straight from this list, so
 * it can't drift from reality. EditorNext's key handler is documented against
 * the same `keys` strings — keep the two in sync when adding a binding.
 */

export interface EditorShortcut {
  keys: string;
  description: string;
}

export const EDITOR_SHORTCUTS: readonly EditorShortcut[] = [
  { keys: 'Space', description: 'Play / pause' },
  { keys: 'J / K / L', description: 'Shuttle reverse / pause / forward (2×, 4×)' },
  { keys: '← / →', description: 'Step 1 frame (Shift: 10)' },
  { keys: ', / .', description: 'Step 1 frame back / forward' },
  { keys: 'I / O', description: 'Set in / out point' },
  { keys: 'M', description: 'Add marker (Shift+M: with note)' },
  { keys: 'S', description: 'Split at playhead (Shift+S: blade all tracks)' },
  { keys: '[ / ]', description: 'Trim start / end to playhead' },
  { keys: 'V / B', description: 'Select / Razor tool' },
  { keys: 'Del', description: 'Ripple-delete selected clip' },
  { keys: 'Ctrl+Z / Ctrl+Y', description: 'Undo / Redo (Ctrl+Shift+Z also redoes)' },
  { keys: '?', description: 'Toggle this help' },
];
