/**
 * Editor persistence — Phase 2, PR 9b. Two local-storage features:
 *
 *  - **Snapshots**: named restore points of a whole timeline. The backend keeps
 *    only the latest edit; snapshots give the user named versions to jump back
 *    to. Per editor scope (episode id, or "sample").
 *  - **Crash-recovery**: a rolling draft of the current timeline so an
 *    unexpected close before the debounced backend autosave isn't lost. On
 *    load the editor offers to restore it when it's newer than the session.
 *
 * Storage is injected (defaults to `localStorage`) so the logic is unit-tested
 * against a fake and stays safe where storage is unavailable.
 */

import { type ProjectTimeline } from './timeline';

export type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export interface EditorSnapshot {
  id: string;
  name: string;
  /** Epoch ms. */
  createdAt: number;
  timeline: ProjectTimeline;
}

export interface RecoveryDraft {
  savedAt: number;
  timeline: ProjectTimeline;
}

const PREFIX = 'drevalis.editor';

export function editorScope(episodeId?: string): string {
  return episodeId ?? 'sample';
}

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch {
    return null;
  }
}

function readJson<T>(storage: StorageLike | null, key: string): T | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeJson(storage: StorageLike | null, key: string, value: unknown): void {
  if (!storage) return;
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota/serialisation failure is non-fatal — recovery is best-effort.
  }
}

// ── Snapshots ────────────────────────────────────────────────────────────────

const snapshotsKey = (scope: string) => `${PREFIX}.snapshots.${scope}`;

export function loadSnapshots(scope: string, storage: StorageLike | null = defaultStorage()): EditorSnapshot[] {
  return readJson<EditorSnapshot[]>(storage, snapshotsKey(scope)) ?? [];
}

export function addSnapshot(
  scope: string,
  name: string,
  timeline: ProjectTimeline,
  storage: StorageLike | null = defaultStorage(),
  opts: { now?: () => number; id?: () => string } = {},
): EditorSnapshot[] {
  const now = opts.now ?? Date.now;
  const makeId = opts.id ?? (() => crypto.randomUUID());
  const snapshot: EditorSnapshot = {
    id: makeId(),
    name: name.trim() || new Date(now()).toLocaleString(),
    createdAt: now(),
    timeline,
  };
  // Newest first.
  const next = [snapshot, ...loadSnapshots(scope, storage)];
  writeJson(storage, snapshotsKey(scope), next);
  return next;
}

export function removeSnapshot(
  scope: string,
  id: string,
  storage: StorageLike | null = defaultStorage(),
): EditorSnapshot[] {
  const next = loadSnapshots(scope, storage).filter((s) => s.id !== id);
  writeJson(storage, snapshotsKey(scope), next);
  return next;
}

// ── Crash-recovery draft ──────────────────────────────────────────────────────

const recoveryKey = (scope: string) => `${PREFIX}.recovery.${scope}`;

export function saveRecovery(
  scope: string,
  timeline: ProjectTimeline,
  storage: StorageLike | null = defaultStorage(),
  now: () => number = Date.now,
): void {
  writeJson(storage, recoveryKey(scope), { savedAt: now(), timeline } satisfies RecoveryDraft);
}

export function loadRecovery(scope: string, storage: StorageLike | null = defaultStorage()): RecoveryDraft | null {
  return readJson<RecoveryDraft>(storage, recoveryKey(scope));
}

export function clearRecovery(scope: string, storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(recoveryKey(scope));
  } catch {
    // ignore
  }
}
