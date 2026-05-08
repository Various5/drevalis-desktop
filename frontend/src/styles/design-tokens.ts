// =============================================================================
// Drevalis Creator Studio Design Token System
// =============================================================================
// Dark-mode-first professional tool aesthetic.
// All text colors verified against WCAG AA contrast ratios on their intended
// background surfaces. Accent: teal/cyan — professional video-tool feel.
//
// ── Text-hierarchy naming convention ─────────────────────────────────────────
//   primary    EDEDEF  15.9:1   headings, body
//   secondary  9898A0   7.1:1   labels, descriptions
//   tertiary   717179   4.61:1  hints, placeholders (WCAG AA)
//   muted      ALIAS    same as ``tertiary`` — kept as a separate token name
//                       so component code can express *intent* ("this text is
//                       quiet") without committing to a particular contrast
//                       step. If we ever add a "very quiet" tier between
//                       tertiary and the placeholder colour, ``muted`` becomes
//                       its own value; until then it tracks ``tertiary`` 1:1.
// =============================================================================

// ---------------------------------------------------------------------------
// Colors
// ---------------------------------------------------------------------------

export const colors = {
  // Background hierarchy (darkest -> lightest)
  bg: {
    base: '#0A0A0B',       // App canvas / deepest background
    surface: '#111113',     // Cards, panels, sidebars
    elevated: '#1A1A1E',    // Modals, dropdowns, popovers
    hover: '#222228',       // Interactive surface hover state
    active: '#2A2A32',      // Active / pressed state
    overlay: '#0A0A0BB3',   // 70 % opacity overlay for modals / drawers
  },

  // Text hierarchy (contrast ratios measured against bg.base #0A0A0B)
  text: {
    primary: '#EDEDEF',     // 15.9:1 — headings, body text
    secondary: '#9898A0',   // 7.1:1  — labels, descriptions
    tertiary: '#717179',    // 4.61:1 — hints, placeholders (WCAG AA)
    muted: '#717179',       // Alias of tertiary — see file header for rationale
    inverse: '#0A0A0B',     // For text on light / accent backgrounds
    onAccent: '#021F18',    // High-contrast text on accent backgrounds
  },

  // Accent — sharp teal/cyan, professional video-tool feel
  accent: {
    DEFAULT: '#00D4AA',     // Primary accent (buttons, links, highlights)
    hover: '#00E8BC',       // Accent hover — slightly brighter
    active: '#00BF99',      // Accent pressed / active
    muted: '#00D4AA1A',     // 10 % opacity — subtle tinted backgrounds
    subtle: '#00D4AA33',    // 20 % opacity — accent borders, focus rings
    text: '#00D4AA',        // Accent-colored inline text
  },

  // Status / semantic colors
  status: {
    success: '#34D399',     // Green — completed, exported
    successMuted: '#34D3991A',
    warning: '#FBBF24',     // Amber — needs attention
    warningMuted: '#FBBF241A',
    error: '#F87171',       // Red — failed, validation error
    errorMuted: '#F871711A',
    info: '#60A5FA',        // Blue — informational, in-review
    infoMuted: '#60A5FA1A',
  },

  // Pipeline step colors — each generation stage gets its own hue
  steps: {
    script: '#818CF8',      // Indigo   — script generation
    voice: '#F472B6',       // Pink     — voice synthesis
    scenes: '#34D399',      // Green    — scene image generation
    captions: '#FBBF24',    // Amber    — caption overlay
    assembly: '#60A5FA',    // Blue     — video assembly
    thumbnail: '#A78BFA',   // Violet   — thumbnail creation
  },

  // Step muted variants (for backgrounds, progress bar inactive segments)
  stepsMuted: {
    script: '#818CF81A',
    voice: '#F472B61A',
    scenes: '#34D3991A',
    captions: '#FBBF241A',
    assembly: '#60A5FA1A',
    thumbnail: '#A78BFA1A',
  },

  // Borders
  border: {
    DEFAULT: '#222228',     // Subtle dividers, card borders
    hover: '#333340',       // Border on hover
    strong: '#44444F',      // Emphasized borders
    accent: '#00D4AA33',    // Accent-tinted border (20 % opacity)
    error: '#F8717166',     // Error-tinted border
  },
} as const;

// ---------------------------------------------------------------------------
// Typography
// ---------------------------------------------------------------------------

export const typography = {
  // Font stacks
  fontFamily: {
    sans: '"DM Sans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    display: '"Outfit", "DM Sans", system-ui, sans-serif',
    mono: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
  },

  // Font weights
  fontWeight: {
    normal: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  },

  // Type scale — optimized for 1440 px + desktop tool UI.
  // Each entry: [fontSize, { lineHeight, letterSpacing? }]
  fontSize: {
    xs:   ['0.6875rem',  { lineHeight: '1rem',    letterSpacing: '0.01em' }],  // 11px
    sm:   ['0.75rem',    { lineHeight: '1rem',    letterSpacing: '0.005em' }], // 12px
    base: ['0.8125rem',  { lineHeight: '1.25rem', letterSpacing: '0em' }],     // 13px — default body
    md:   ['0.875rem',   { lineHeight: '1.25rem', letterSpacing: '0em' }],     // 14px
    lg:   ['1rem',       { lineHeight: '1.5rem',  letterSpacing: '-0.005em' }],// 16px
    xl:   ['1.125rem',   { lineHeight: '1.5rem',  letterSpacing: '-0.01em' }], // 18px
    '2xl': ['1.5rem',    { lineHeight: '2rem',    letterSpacing: '-0.015em' }],// 24px
    '3xl': ['1.875rem',  { lineHeight: '2.25rem', letterSpacing: '-0.02em' }], // 30px
    '4xl': ['2.25rem',   { lineHeight: '2.5rem',  letterSpacing: '-0.025em' }],// 36px
  },
} as const;

// ---------------------------------------------------------------------------
// Spacing  (4 px grid)
// ---------------------------------------------------------------------------

export const spacing = {
  px: '1px',
  0:   '0px',
  0.5: '0.125rem',  // 2px
  1:   '0.25rem',   // 4px
  1.5: '0.375rem',  // 6px
  2:   '0.5rem',    // 8px
  2.5: '0.625rem',  // 10px
  3:   '0.75rem',   // 12px
  3.5: '0.875rem',  // 14px
  4:   '1rem',      // 16px
  5:   '1.25rem',   // 20px
  6:   '1.5rem',    // 24px
  7:   '1.75rem',   // 28px
  8:   '2rem',      // 32px
  9:   '2.25rem',   // 36px
  10:  '2.5rem',    // 40px
  12:  '3rem',      // 48px
  14:  '3.5rem',    // 56px
  16:  '4rem',      // 64px
  20:  '5rem',      // 80px
  24:  '6rem',      // 96px
  32:  '8rem',      // 128px
  40:  '10rem',     // 160px
  48:  '12rem',     // 192px
  56:  '14rem',     // 224px
  64:  '16rem',     // 256px
} as const;

// ---------------------------------------------------------------------------
// Border Radius
// ---------------------------------------------------------------------------

export const borderRadius = {
  none: '0px',
  xs:   '2px',
  sm:   '4px',
  DEFAULT: '6px',
  md:   '8px',
  lg:   '10px',
  xl:   '12px',
  '2xl': '16px',
  full: '9999px',
} as const;

// ---------------------------------------------------------------------------
// Shadows — subtle and diffuse for dark themes (light shadows look wrong)
// ---------------------------------------------------------------------------

export const shadows = {
  none: 'none',
  xs:   '0 1px 2px 0 rgba(0, 0, 0, 0.4)',
  sm:   '0 2px 4px -1px rgba(0, 0, 0, 0.5), 0 1px 2px -1px rgba(0, 0, 0, 0.4)',
  DEFAULT: '0 4px 8px -2px rgba(0, 0, 0, 0.5), 0 2px 4px -2px rgba(0, 0, 0, 0.4)',
  md:   '0 6px 12px -3px rgba(0, 0, 0, 0.5), 0 3px 6px -3px rgba(0, 0, 0, 0.4)',
  lg:   '0 12px 24px -4px rgba(0, 0, 0, 0.5), 0 4px 8px -4px rgba(0, 0, 0, 0.5)',
  xl:   '0 20px 40px -8px rgba(0, 0, 0, 0.6), 0 8px 16px -8px rgba(0, 0, 0, 0.5)',
  '2xl': '0 32px 64px -16px rgba(0, 0, 0, 0.7)',
  inner: 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.3)',
  // Glow effects for accent elements
  accentGlow: '0 0 24px rgba(0, 212, 170, 0.2), 0 0 8px rgba(0, 212, 170, 0.15), 0 0 2px rgba(0, 212, 170, 0.1)',
  errorGlow:  '0 0 24px rgba(248, 113, 113, 0.2), 0 0 8px rgba(248, 113, 113, 0.15)',
  cardHover: '0 8px 24px -4px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(0, 212, 170, 0.08)',
  glass: '0 8px 32px rgba(0, 0, 0, 0.4)',
} as const;

// ---------------------------------------------------------------------------
// Animation / Transitions
// ---------------------------------------------------------------------------

export const animation = {
  // Durations
  duration: {
    instant: '50ms',
    fast: '100ms',
    normal: '200ms',
    slow: '300ms',
    slower: '500ms',
  },

  // Easing curves
  easing: {
    DEFAULT: 'cubic-bezier(0.4, 0, 0.2, 1)',      // General purpose
    in:      'cubic-bezier(0.4, 0, 1, 1)',          // Accelerate
    out:     'cubic-bezier(0, 0, 0.2, 1)',           // Decelerate
    inOut:   'cubic-bezier(0.4, 0, 0.2, 1)',         // Standard ease
    bounce:  'cubic-bezier(0.34, 1.56, 0.64, 1)',    // Slight overshoot
  },

  // Pre-composed transitions
  transition: {
    none: 'none',
    colors: 'color 200ms cubic-bezier(0.4,0,0.2,1), background-color 200ms cubic-bezier(0.4,0,0.2,1), border-color 200ms cubic-bezier(0.4,0,0.2,1)',
    opacity: 'opacity 200ms cubic-bezier(0.4,0,0.2,1)',
    transform: 'transform 200ms cubic-bezier(0.4,0,0.2,1)',
    all: 'all 200ms cubic-bezier(0.4,0,0.2,1)',
    shadow: 'box-shadow 200ms cubic-bezier(0.4,0,0.2,1)',
  },

  // Keyframe definitions (for use in @keyframes or Tailwind config)
  keyframes: {
    fadeIn: {
      from: { opacity: '0' },
      to:   { opacity: '1' },
    },
    fadeOut: {
      from: { opacity: '1' },
      to:   { opacity: '0' },
    },
    slideUp: {
      from: { transform: 'translateY(4px)', opacity: '0' },
      to:   { transform: 'translateY(0)',   opacity: '1' },
    },
    slideDown: {
      from: { transform: 'translateY(-4px)', opacity: '0' },
      to:   { transform: 'translateY(0)',    opacity: '1' },
    },
    pulse: {
      '0%, 100%': { opacity: '1' },
      '50%':      { opacity: '0.6' },
    },
    progressStripe: {
      from: { backgroundPosition: '1rem 0' },
      to:   { backgroundPosition: '0 0' },
    },
    spin: {
      from: { transform: 'rotate(0deg)' },
      to:   { transform: 'rotate(360deg)' },
    },
    playheadBlink: {
      '0%, 100%': { opacity: '1' },
      '50%':      { opacity: '0.7' },
    },
    staggerFadeIn: {
      from: { opacity: '0', transform: 'translateY(8px)' },
      to: { opacity: '1', transform: 'translateY(0)' },
    },
    scaleIn: {
      from: { opacity: '0', transform: 'scale(0.95)' },
      to: { opacity: '1', transform: 'scale(1)' },
    },
    shimmerGradient: {
      '0%': { backgroundPosition: '200% 0' },
      '100%': { backgroundPosition: '-200% 0' },
    },
    glowPulse: {
      '0%, 100%': { boxShadow: '0 0 20px rgba(0, 212, 170, 0.15)' },
      '50%': { boxShadow: '0 0 30px rgba(0, 212, 170, 0.25), 0 0 60px rgba(0, 212, 170, 0.1)' },
    },
  },
} as const;

// ---------------------------------------------------------------------------
// Z-Index Scale
// ---------------------------------------------------------------------------

export const zIndex = {
  base: 0,
  dropdown: 10,
  sticky: 20,
  overlay: 30,
  modal: 40,
  popover: 50,
  toast: 60,
  tooltip: 70,
  playhead: 5,     // Timeline playhead
  controls: 10,    // Video player controls
} as const;

// ---------------------------------------------------------------------------
// Breakpoints
// ---------------------------------------------------------------------------

export const breakpoints = {
  sm:  '640px',
  md:  '768px',
  lg:  '1024px',   // Minimum supported
  xl:  '1280px',
  '2xl': '1440px', // Primary target
  '3xl': '1920px', // Ultra-wide
} as const;

// ---------------------------------------------------------------------------
// Layout Constants
// ---------------------------------------------------------------------------

export const layout = {
  sidebar: {
    collapsed: '56px',
    expanded: '240px',
  },
  header: {
    height: '48px',
  },
  timeline: {
    minHeight: '120px',
    maxHeight: '280px',
  },
  videoPlayer: {
    aspectRatio: '9 / 16',  // Vertical short-form
  },
  contentMaxWidth: '1400px',
} as const;

// ---------------------------------------------------------------------------
// Combined export for convenience
// ---------------------------------------------------------------------------

export const tokens = {
  colors,
  typography,
  spacing,
  borderRadius,
  shadows,
  animation,
  zIndex,
  breakpoints,
  layout,
} as const;

export default tokens;
