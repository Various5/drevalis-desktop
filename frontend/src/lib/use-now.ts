// Shared 1-Hz tick for elapsed-time UI.
//
// JobProgressBar and other "show time-since-X" components each owned
// a per-instance setInterval. With ~8 active jobs that's 8 timers
// per tick, 8 React updates per second, 8 reconciliations.
//
// useNow() hands every consumer the same Date.now() value sourced
// from a single shared interval. The interval only runs while at
// least one consumer is mounted; the last unmount tears it down.

import { useEffect, useState } from 'react';

const FALLBACK_INTERVAL_MS = 1000;

let listeners: Set<(now: number) => void> = new Set();
let timer: ReturnType<typeof setInterval> | null = null;
let intervalMs = FALLBACK_INTERVAL_MS;

function start() {
  if (timer !== null) return;
  timer = setInterval(() => {
    const now = Date.now();
    for (const fn of listeners) fn(now);
  }, intervalMs);
}

function stop() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

export function useNow(intervalMsOverride: number = FALLBACK_INTERVAL_MS): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    // First subscriber sets the interval; later subscribers reuse it.
    if (listeners.size === 0) {
      intervalMs = intervalMsOverride;
      start();
    }
    listeners.add(setNow);
    return () => {
      listeners.delete(setNow);
      if (listeners.size === 0) stop();
    };
  }, [intervalMsOverride]);

  return now;
}
