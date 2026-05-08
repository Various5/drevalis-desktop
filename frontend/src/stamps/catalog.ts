// Stamp catalog (v0.21.0)
//
// Bundled overlay presets that ship inside the frontend bundle. Unlike
// user-uploaded assets these don't go through the asset upload pipeline
// — they're plain static SVGs served from /stamps/. The video editor's
// timeline drop handler routes them through the same image-overlay
// path as a regular asset, just with a public URL instead of an
// /api/v1/assets/{id}/file URL.
//
// Adding a new stamp: drop the SVG in frontend/public/stamps/{cat}/
// and add an entry below.

export type StampCategory =
  | 'emoji'
  | 'lower-thirds'
  | 'social-cta'
  | 'transitions';

export interface StampEntry {
  id: string;
  category: StampCategory;
  label: string;
  url: string;          // path served by the frontend host, e.g. /stamps/emoji/fire.svg
  description?: string;
  // Default size hint applied when the stamp is dropped into the
  // editor. Stored on the EditTimelineClip's overlay slot. The
  // FFmpeg overlay filter respects width=auto (px); height is
  // proportional unless explicitly set.
  defaultDurationSeconds?: number;
}

export const STAMP_CATEGORY_LABELS: Record<StampCategory, string> = {
  emoji: 'Emoji & Stickers',
  'lower-thirds': 'Lower Thirds',
  'social-cta': 'Social CTAs',
  transitions: 'Transitions',
};

export const STAMP_CATALOG: StampEntry[] = [
  // ── Emoji / sticker style overlays ─────────────────────────────
  {
    id: 'fire',
    category: 'emoji',
    label: 'Fire',
    url: '/stamps/emoji/fire.svg',
    description: 'Hot-take emphasis flame.',
  },
  {
    id: 'sparkle',
    category: 'emoji',
    label: 'Sparkle',
    url: '/stamps/emoji/sparkle.svg',
    description: 'Magic / wow moment.',
  },
  {
    id: 'heart',
    category: 'emoji',
    label: 'Heart',
    url: '/stamps/emoji/heart.svg',
    description: 'Love / soft moment.',
  },
  {
    id: 'eyes',
    category: 'emoji',
    label: 'Eyes',
    url: '/stamps/emoji/eyes.svg',
    description: 'Suspicious / "look at this".',
  },
  {
    id: 'hundred',
    category: 'emoji',
    label: '100',
    url: '/stamps/emoji/hundred.svg',
    description: 'Top tier emphasis.',
  },

  // ── Lower-third title cards ────────────────────────────────────
  {
    id: 'lt-solid',
    category: 'lower-thirds',
    label: 'Solid',
    url: '/stamps/lower-thirds/solid.svg',
    description: 'Black bar with red accent.',
    defaultDurationSeconds: 5,
  },
  {
    id: 'lt-gradient',
    category: 'lower-thirds',
    label: 'Gradient',
    url: '/stamps/lower-thirds/gradient.svg',
    description: 'Blue → violet fade-out.',
    defaultDurationSeconds: 5,
  },
  {
    id: 'lt-breaking',
    category: 'lower-thirds',
    label: 'Breaking news',
    url: '/stamps/lower-thirds/breaking.svg',
    description: 'Red "BREAKING" tag + headline.',
    defaultDurationSeconds: 5,
  },

  // ── Social CTAs ────────────────────────────────────────────────
  {
    id: 'cta-subscribe',
    category: 'social-cta',
    label: 'Subscribe',
    url: '/stamps/social-cta/subscribe.svg',
    description: 'YouTube-style red Subscribe pill.',
    defaultDurationSeconds: 4,
  },
  {
    id: 'cta-follow',
    category: 'social-cta',
    label: 'Follow',
    url: '/stamps/social-cta/follow.svg',
    description: 'Instagram-gradient Follow pill.',
    defaultDurationSeconds: 4,
  },
  {
    id: 'cta-link-in-bio',
    category: 'social-cta',
    label: 'Link in bio',
    url: '/stamps/social-cta/link-in-bio.svg',
    description: 'Generic link-in-bio dark card.',
    defaultDurationSeconds: 4,
  },

  // ── Transitions (full-frame flashes) ──────────────────────────
  {
    id: 'tr-flash',
    category: 'transitions',
    label: 'White flash',
    url: '/stamps/transitions/flash.svg',
    description: 'Brief full-frame white flash for cuts.',
    defaultDurationSeconds: 0.2,
  },
  {
    id: 'tr-fade-black',
    category: 'transitions',
    label: 'Fade to black',
    url: '/stamps/transitions/fade-black.svg',
    description: 'Solid black frame for fade-outs.',
    defaultDurationSeconds: 0.5,
  },
];

export function findStampById(id: string): StampEntry | null {
  return STAMP_CATALOG.find((s) => s.id === id) ?? null;
}
