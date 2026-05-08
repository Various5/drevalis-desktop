import type { Config } from 'tailwindcss';
import {
  colors,
  typography,
  spacing,
  borderRadius,
  shadows,
  animation,
  zIndex,
  breakpoints,
} from './src/styles/design-tokens';

const config: Config = {
  // ---------------------------------------------------------------------------
  // Dark mode via class — allows explicit toggling (always dark for v1)
  // ---------------------------------------------------------------------------
  darkMode: 'class',

  // ---------------------------------------------------------------------------
  // Content paths
  // ---------------------------------------------------------------------------
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
    './index.html',
  ],

  // ---------------------------------------------------------------------------
  // Theme
  // ---------------------------------------------------------------------------
  theme: {
    // Override screens with our breakpoints
    screens: {
      sm: breakpoints.sm,
      md: breakpoints.md,
      lg: breakpoints.lg,
      xl: breakpoints.xl,
      '2xl': breakpoints['2xl'],
      '3xl': breakpoints['3xl'],
    },

    extend: {
      // -------------------------------------------------------------------
      // Colors
      // -------------------------------------------------------------------
      colors: {
        // Background hierarchy — CSS variables for dark/light theming
        bg: {
          base: 'var(--color-bg-base)',
          surface: 'var(--color-bg-surface)',
          elevated: 'var(--color-bg-elevated)',
          hover: 'var(--color-bg-hover)',
          active: 'var(--color-bg-active)',
          overlay: 'var(--color-bg-overlay)',
        },

        // Text hierarchy — CSS variables for dark/light theming
        txt: {
          primary: 'var(--color-text-primary)',
          secondary: 'var(--color-text-secondary)',
          tertiary: 'var(--color-text-tertiary)',
          // ``muted`` is currently an alias for ``tertiary``. Tracked
          // through a dedicated CSS var so theme presets that want to
          // dial them apart can override one without touching the other.
          // See ``design-tokens.ts`` header for the convention.
          muted: 'var(--color-text-muted)',
          inverse: 'var(--color-text-inverse)',
          onAccent: 'var(--color-text-on-accent)',
        },

        // Accent — CSS variables for dynamic accent color
        accent: {
          DEFAULT: 'var(--color-accent)',
          hover: 'var(--color-accent-hover)',
          active: 'var(--color-accent-active)',
          muted: 'var(--color-accent-muted)',
          subtle: 'var(--color-accent-subtle)',
          text: 'var(--color-accent)',
        },

        // Status — CSS variables for dark/light theming
        success: 'var(--color-success)',
        'success-muted': colors.status.successMuted,
        warning: 'var(--color-warning)',
        'warning-muted': colors.status.warningMuted,
        error: 'var(--color-error)',
        'error-muted': colors.status.errorMuted,
        info: 'var(--color-info)',
        'info-muted': colors.status.infoMuted,

        // Pipeline steps — CSS variables for dark/light theming
        step: {
          script: 'var(--color-step-script)',
          voice: 'var(--color-step-voice)',
          scenes: 'var(--color-step-scenes)',
          captions: 'var(--color-step-captions)',
          assembly: 'var(--color-step-assembly)',
          thumbnail: 'var(--color-step-thumbnail)',
        },
        'step-muted': {
          script: colors.stepsMuted.script,
          voice: colors.stepsMuted.voice,
          scenes: colors.stepsMuted.scenes,
          captions: colors.stepsMuted.captions,
          assembly: colors.stepsMuted.assembly,
          thumbnail: colors.stepsMuted.thumbnail,
        },

        // Borders — CSS variables for dark/light theming
        border: {
          DEFAULT: 'var(--color-border)',
          hover: 'var(--color-border-hover)',
          strong: 'var(--color-border-strong)',
          accent: 'var(--color-border-accent)',
          error: colors.border.error,
        },
      },

      // -------------------------------------------------------------------
      // Typography
      // -------------------------------------------------------------------
      fontFamily: {
        sans: [typography.fontFamily.sans],
        display: [typography.fontFamily.display],
        mono: [typography.fontFamily.mono],
      },

      fontSize: Object.fromEntries(
        Object.entries(typography.fontSize).map(([key, value]) => [
          key,
          value as [string, { lineHeight: string; letterSpacing?: string }],
        ]),
      ),

      fontWeight: typography.fontWeight,

      // -------------------------------------------------------------------
      // Spacing (4 px grid)
      // -------------------------------------------------------------------
      spacing: Object.fromEntries(
        Object.entries(spacing).map(([key, value]) => [String(key), value]),
      ),

      // -------------------------------------------------------------------
      // Border Radius
      // -------------------------------------------------------------------
      borderRadius: {
        none: borderRadius.none,
        xs: borderRadius.xs,
        sm: borderRadius.sm,
        DEFAULT: borderRadius.DEFAULT,
        md: borderRadius.md,
        lg: borderRadius.lg,
        xl: borderRadius.xl,
        '2xl': borderRadius['2xl'],
        full: borderRadius.full,
      },

      // -------------------------------------------------------------------
      // Box Shadow
      // -------------------------------------------------------------------
      boxShadow: {
        none: shadows.none,
        xs: shadows.xs,
        sm: shadows.sm,
        DEFAULT: shadows.DEFAULT,
        md: shadows.md,
        lg: shadows.lg,
        xl: shadows.xl,
        '2xl': shadows['2xl'],
        inner: shadows.inner,
        'accent-glow': shadows.accentGlow,
        'error-glow': shadows.errorGlow,
        'card-hover': shadows.cardHover,
        glass: shadows.glass,
      },

      // -------------------------------------------------------------------
      // Z-Index
      // -------------------------------------------------------------------
      zIndex: Object.fromEntries(
        Object.entries(zIndex).map(([key, value]) => [key, String(value)]),
      ),

      // -------------------------------------------------------------------
      // Transitions
      // -------------------------------------------------------------------
      transitionDuration: {
        instant: animation.duration.instant,
        fast: animation.duration.fast,
        normal: animation.duration.normal,
        slow: animation.duration.slow,
        slower: animation.duration.slower,
      },

      transitionTimingFunction: {
        DEFAULT: animation.easing.DEFAULT,
        in: animation.easing.in,
        out: animation.easing.out,
        'in-out': animation.easing.inOut,
        bounce: animation.easing.bounce,
      },

      // -------------------------------------------------------------------
      // Keyframes & Animations
      // -------------------------------------------------------------------
      keyframes: {
        'fade-in': animation.keyframes.fadeIn,
        'fade-out': animation.keyframes.fadeOut,
        'slide-up': animation.keyframes.slideUp,
        'slide-down': animation.keyframes.slideDown,
        pulse: animation.keyframes.pulse,
        'progress-stripe': animation.keyframes.progressStripe,
        spin: animation.keyframes.spin,
        'playhead-blink': animation.keyframes.playheadBlink,
        'stagger-fade-in': animation.keyframes.staggerFadeIn,
        'scale-in': animation.keyframes.scaleIn,
        'shimmer-gradient': animation.keyframes.shimmerGradient,
        'glow-pulse': animation.keyframes.glowPulse,
      },

      animation: {
        'fade-in':         'fade-in 200ms cubic-bezier(0.4,0,0.2,1)',
        'fade-out':        'fade-out 200ms cubic-bezier(0.4,0,0.2,1)',
        'slide-up':        'slide-up 200ms cubic-bezier(0,0,0.2,1)',
        'slide-down':      'slide-down 200ms cubic-bezier(0,0,0.2,1)',
        pulse:             'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite',
        'progress-stripe': 'progress-stripe 1s linear infinite',
        spin:              'spin 1s linear infinite',
        'playhead-blink':  'playhead-blink 1.2s ease-in-out infinite',
        'stagger-fade-in': 'stagger-fade-in 400ms cubic-bezier(0,0,0.2,1) both',
        'scale-in':        'scale-in 200ms cubic-bezier(0,0,0.2,1)',
        'glow-pulse':      'glow-pulse 3s ease-in-out infinite',
        'shimmer-gradient': 'shimmer-gradient 2s ease-in-out infinite',
      },

      // -------------------------------------------------------------------
      // Aspect Ratio
      // -------------------------------------------------------------------
      aspectRatio: {
        'video-short': '9 / 16',
        'video-wide':  '16 / 9',
      },
    },
  },

  // ---------------------------------------------------------------------------
  // Plugins
  // ---------------------------------------------------------------------------
  plugins: [],
};

export default config;
