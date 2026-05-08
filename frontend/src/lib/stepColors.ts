/**
 * Canonical color palette for the six pipeline steps.
 *
 * Every page that renders a step badge / step-colored row must import
 * from here. Previously each page hardcoded its own palette (Logs used
 * blue for "script" while Jobs used indigo) which left users staring
 * at the same step in different colors across the app.
 */

export type StepName =
  | 'script'
  | 'voice'
  | 'scenes'
  | 'captions'
  | 'assembly'
  | 'thumbnail';

/** Text color (foreground). Matches the Badge variants in components/ui/Badge.tsx. */
export const STEP_TEXT: Record<StepName, string> = {
  script: 'text-step-script',
  voice: 'text-step-voice',
  scenes: 'text-step-scenes',
  captions: 'text-step-captions',
  assembly: 'text-step-assembly',
  thumbnail: 'text-step-thumbnail',
};

/** Solid background (used for progress bars / dots). */
export const STEP_BG: Record<StepName, string> = {
  script: 'bg-step-script',
  voice: 'bg-step-voice',
  scenes: 'bg-step-scenes',
  captions: 'bg-step-captions',
  assembly: 'bg-step-assembly',
  thumbnail: 'bg-step-thumbnail',
};

/** Muted background for soft chips / row highlights. */
export const STEP_MUTED: Record<StepName, string> = {
  script: 'bg-step-muted-script',
  voice: 'bg-step-muted-voice',
  scenes: 'bg-step-muted-scenes',
  captions: 'bg-step-muted-captions',
  assembly: 'bg-step-muted-assembly',
  thumbnail: 'bg-step-muted-thumbnail',
};

/** Order in which steps run — use for sorting UI rows. */
export const STEP_ORDER: readonly StepName[] = [
  'script',
  'voice',
  'scenes',
  'captions',
  'assembly',
  'thumbnail',
] as const;

export function isKnownStep(s: string): s is StepName {
  return (STEP_ORDER as readonly string[]).includes(s);
}
