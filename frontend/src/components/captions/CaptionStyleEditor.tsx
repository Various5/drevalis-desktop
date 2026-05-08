import { useState, useCallback, useEffect, useRef } from 'react';
import { Select } from '@/components/ui/Select';
import type { CaptionStyle } from '@/types';

// ---------------------------------------------------------------------------
// Default style
// ---------------------------------------------------------------------------

export const DEFAULT_CAPTION_STYLE: CaptionStyle = {
  preset: 'youtube_highlight',
  font_name: 'Arial',
  font_size: 72,
  primary_color: '#FFFFFF',
  highlight_color: '#00D4AA',
  outline_color: '#000000',
  outline_width: 4,
  position: 'bottom',
  margin_v: 200,
  animation: 'fade',
  words_per_line: 3,
  uppercase: true,
};

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

interface PresetInfo {
  key: CaptionStyle['preset'];
  name: string;
  description: string;
  style: Partial<CaptionStyle>;
}

const PRESETS: PresetInfo[] = [
  {
    key: 'youtube_highlight',
    name: 'YouTube Highlight',
    description: 'Active word highlighted, bold and punchy',
    style: {
      font_name: 'Arial',
      font_size: 72,
      primary_color: '#FFFFFF',
      highlight_color: '#00D4AA',
      outline_color: '#000000',
      outline_width: 4,
      position: 'bottom',
      animation: 'fade',
      words_per_line: 3,
      uppercase: true,
    },
  },
  {
    key: 'karaoke',
    name: 'Karaoke',
    description: 'Words light up as they are spoken',
    style: {
      font_name: 'Impact',
      font_size: 64,
      primary_color: '#999999',
      highlight_color: '#FFD700',
      outline_color: '#000000',
      outline_width: 3,
      position: 'bottom',
      animation: 'none',
      words_per_line: 4,
      uppercase: true,
    },
  },
  {
    key: 'tiktok_pop',
    name: 'TikTok Pop',
    description: 'Colorful pop-in, center screen',
    style: {
      font_name: 'Montserrat',
      font_size: 80,
      primary_color: '#FFFFFF',
      highlight_color: '#FF6B9D',
      outline_color: '#1A1A2E',
      outline_width: 5,
      position: 'center',
      animation: 'pop',
      words_per_line: 2,
      uppercase: true,
    },
  },
  {
    key: 'minimal',
    name: 'Minimal',
    description: 'Clean, small, unobtrusive subtitles',
    style: {
      font_name: 'Arial',
      font_size: 48,
      primary_color: '#EDEDEF',
      highlight_color: '#EDEDEF',
      outline_color: '#000000',
      outline_width: 2,
      position: 'bottom',
      animation: 'fade',
      words_per_line: 6,
      uppercase: false,
    },
  },
  {
    key: 'classic',
    name: 'Classic',
    description: 'Traditional subtitle style, yellow text',
    style: {
      font_name: 'Arial',
      font_size: 56,
      primary_color: '#FFFF00',
      highlight_color: '#FFFF00',
      outline_color: '#000000',
      outline_width: 3,
      position: 'bottom',
      animation: 'none',
      words_per_line: 5,
      uppercase: false,
    },
  },
];

// ---------------------------------------------------------------------------
// Font options
// ---------------------------------------------------------------------------

const FONT_OPTIONS = [
  { value: 'Arial', label: 'Arial' },
  { value: 'Impact', label: 'Impact' },
  { value: 'Montserrat', label: 'Montserrat' },
  { value: 'Arial Black', label: 'Arial Black' },
  { value: 'Bebas Neue', label: 'Bebas Neue' },
  { value: 'Anton', label: 'Anton' },
  { value: 'Oswald', label: 'Oswald' },
];

const WORDS_PER_LINE_OPTIONS = [
  { value: '2', label: '2 words' },
  { value: '3', label: '3 words' },
  { value: '4', label: '4 words' },
  { value: '5', label: '5 words' },
  { value: '6', label: '6 words' },
];

const POSITION_OPTIONS: Array<{ value: CaptionStyle['position']; label: string }> = [
  { value: 'bottom', label: 'Bottom' },
  { value: 'center', label: 'Center' },
  { value: 'top', label: 'Top' },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CaptionStyleEditorProps {
  value: CaptionStyle;
  onChange: (style: CaptionStyle) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function CaptionStyleEditor({ value, onChange }: CaptionStyleEditorProps) {
  const [animKey, setAnimKey] = useState(0);
  const previewRef = useRef<HTMLDivElement>(null);

  const update = useCallback(
    (patch: Partial<CaptionStyle>) => {
      onChange({ ...value, ...patch });
    },
    [value, onChange],
  );

  const selectPreset = useCallback(
    (preset: PresetInfo) => {
      onChange({ ...value, ...preset.style, preset: preset.key });
      setAnimKey((k) => k + 1);
    },
    [value, onChange],
  );

  // Trigger re-animation when preset changes
  useEffect(() => {
    setAnimKey((k) => k + 1);
  }, [value.preset]);

  // ---- Preview text ----
  const sampleWords = value.uppercase
    ? ['THIS', 'IS', 'A', 'SAMPLE', 'CAPTION']
    : ['This', 'is', 'a', 'sample', 'caption'];

  const previewFontSize = Math.max(10, Math.min(value.font_size / 5, 22));

  return (
    <div className="space-y-6">
      {/* Preset selector */}
      <div>
        <label className="text-xs font-medium text-txt-secondary block mb-2">
          Style Preset
        </label>
        <div className="grid grid-cols-5 gap-3">
          {PRESETS.map((preset) => {
            const isActive = value.preset === preset.key;
            return (
              <button
                key={preset.key}
                type="button"
                onClick={() => selectPreset(preset)}
                className={[
                  'flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all duration-fast',
                  'hover:bg-bg-hover',
                  isActive
                    ? 'border-accent bg-accent-muted shadow-accent-glow'
                    : 'border-border bg-bg-surface',
                ].join(' ')}
              >
                {/* Mini preview swatch */}
                <PresetSwatch preset={preset} />
                <div className="text-center">
                  <p
                    className={[
                      'text-xs font-semibold',
                      isActive ? 'text-accent' : 'text-txt-primary',
                    ].join(' ')}
                  >
                    {preset.name}
                  </p>
                  <p className="text-[10px] text-txt-tertiary mt-0.5 leading-tight">
                    {preset.description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Left: Controls */}
        <div className="col-span-7 space-y-5">
          {/* Font & Size row */}
          <div className="grid grid-cols-2 gap-4">
            <Select
              label="Font"
              value={value.font_name}
              onChange={(e) => update({ font_name: e.target.value })}
              options={FONT_OPTIONS}
            />
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-txt-secondary">
                Font Size: {value.font_size}px
              </label>
              <div className="flex items-center gap-3 h-8">
                <input
                  type="range"
                  min={36}
                  max={120}
                  value={value.font_size}
                  onChange={(e) =>
                    update({ font_size: Number(e.target.value) })
                  }
                  className="w-full accent-accent h-1.5 bg-bg-elevated rounded-full appearance-none cursor-pointer
                    [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                    [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-sm
                    [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-bg-base"
                />
                <span className="text-xs text-txt-tertiary font-mono w-8 text-right shrink-0">
                  {value.font_size}
                </span>
              </div>
            </div>
          </div>

          {/* Colors row */}
          <div>
            <label className="text-xs font-medium text-txt-secondary block mb-2">
              Colors
            </label>
            <div className="grid grid-cols-3 gap-4">
              <ColorInput
                label="Primary"
                value={value.primary_color}
                onChange={(c) => update({ primary_color: c })}
              />
              <ColorInput
                label="Highlight"
                value={value.highlight_color}
                onChange={(c) => update({ highlight_color: c })}
              />
              <ColorInput
                label="Outline"
                value={value.outline_color}
                onChange={(c) => update({ outline_color: c })}
              />
            </div>
          </div>

          {/* Position radio group */}
          <div>
            <label className="text-xs font-medium text-txt-secondary block mb-2">
              Position
            </label>
            <div className="flex gap-2">
              {POSITION_OPTIONS.map((opt) => {
                const isActive = value.position === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => update({ position: opt.value })}
                    className={[
                      'flex-1 h-8 text-xs font-medium rounded border transition-all duration-fast',
                      isActive
                        ? 'bg-accent text-txt-onAccent border-accent'
                        : 'bg-bg-elevated text-txt-secondary border-border hover:border-border-hover hover:bg-bg-hover',
                    ].join(' ')}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Words per line & Outline width */}
          <div className="grid grid-cols-2 gap-4">
            <Select
              label="Words per Line"
              value={String(value.words_per_line)}
              onChange={(e) =>
                update({ words_per_line: Number(e.target.value) })
              }
              options={WORDS_PER_LINE_OPTIONS}
            />
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-txt-secondary">
                Outline Width: {value.outline_width}px
              </label>
              <div className="flex items-center gap-3 h-8">
                <input
                  type="range"
                  min={0}
                  max={10}
                  value={value.outline_width}
                  onChange={(e) =>
                    update({ outline_width: Number(e.target.value) })
                  }
                  className="w-full accent-accent h-1.5 bg-bg-elevated rounded-full appearance-none cursor-pointer
                    [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                    [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-sm
                    [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-bg-base"
                />
                <span className="text-xs text-txt-tertiary font-mono w-8 text-right shrink-0">
                  {value.outline_width}
                </span>
              </div>
            </div>
          </div>

          {/* Uppercase toggle */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => update({ uppercase: !value.uppercase })}
              className={[
                'relative w-9 h-5 rounded-full transition-colors duration-fast',
                value.uppercase ? 'bg-accent' : 'bg-bg-active',
              ].join(' ')}
            >
              <span
                className={[
                  'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-fast',
                  value.uppercase ? 'translate-x-4' : 'translate-x-0.5',
                ].join(' ')}
              />
            </button>
            <label className="text-xs font-medium text-txt-secondary">
              Uppercase
            </label>
          </div>
        </div>

        {/* Right: Live Preview */}
        <div className="col-span-5">
          <label className="text-xs font-medium text-txt-secondary block mb-2">
            Live Preview
          </label>
          <div
            ref={previewRef}
            className="relative rounded-lg overflow-hidden border border-border"
            style={{
              aspectRatio: '9 / 16',
              background:
                'linear-gradient(180deg, #1a1a2e 0%, #16213e 40%, #0f3460 100%)',
            }}
          >
            {/* Simulated video content placeholder */}
            <div className="absolute inset-0 flex items-center justify-center opacity-10">
              <svg
                width="48"
                height="48"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1"
                className="text-white"
              >
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            </div>

            {/* Caption text */}
            <div
              key={animKey}
              className={[
                'absolute left-0 right-0 flex justify-center px-3',
                value.position === 'top'
                  ? 'top-[12%]'
                  : value.position === 'center'
                    ? 'top-1/2 -translate-y-1/2'
                    : 'bottom-[15%]',
              ].join(' ')}
              style={{
                animation:
                  value.animation === 'fade'
                    ? 'fadeIn 0.4s ease-out'
                    : value.animation === 'pop'
                      ? 'popIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)'
                      : value.animation === 'bounce'
                        ? 'bounceIn 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)'
                        : 'none',
              }}
            >
              <div
                className="text-center leading-relaxed font-bold"
                style={{
                  fontFamily: value.font_name,
                  fontSize: `${previewFontSize}px`,
                  WebkitTextStroke: `${Math.max(1, value.outline_width / 3)}px ${value.outline_color}`,
                  paintOrder: 'stroke fill',
                }}
              >
                {renderPreviewWords(sampleWords, value)}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Inline keyframe styles */}
      <style>{`
        @keyframes popIn {
          0% { transform: scale(0.5); opacity: 0; }
          100% { transform: scale(1); opacity: 1; }
        }
        @keyframes bounceIn {
          0% { transform: translateY(20px) scale(0.9); opacity: 0; }
          60% { transform: translateY(-4px) scale(1.02); opacity: 1; }
          100% { transform: translateY(0) scale(1); opacity: 1; }
        }
        @keyframes fadeIn {
          0% { opacity: 0; }
          100% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Preview word renderer
// ---------------------------------------------------------------------------

function renderPreviewWords(words: string[], style: CaptionStyle) {
  // For youtube_highlight: first 2 words in highlight, rest in primary
  // For karaoke: first 3 words in highlight (lit up), rest dimmed
  // For others: all in primary
  return (
    <span>
      {words.map((word, i) => {
        let color = style.primary_color;
        if (
          (style.preset === 'youtube_highlight' || style.preset === 'tiktok_pop') &&
          i < 2
        ) {
          color = style.highlight_color;
        } else if (style.preset === 'karaoke' && i < 3) {
          color = style.highlight_color;
        }
        return (
          <span key={i} style={{ color }}>
            {word}
            {i < words.length - 1 ? ' ' : ''}
          </span>
        );
      })}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Preset swatch — mini visual preview
// ---------------------------------------------------------------------------

function PresetSwatch({ preset }: { preset: PresetInfo }) {
  const primary = preset.style.primary_color ?? '#FFFFFF';
  const highlight = preset.style.highlight_color ?? '#00D4AA';
  const outline = preset.style.outline_color ?? '#000000';

  return (
    <div
      className="w-full h-10 rounded flex items-end justify-center pb-1 relative overflow-hidden"
      style={{
        background: 'linear-gradient(180deg, #1a1a2e 0%, #0f3460 100%)',
      }}
    >
      <div className="flex gap-0.5 items-center">
        <span
          className="text-[7px] font-bold"
          style={{
            color: highlight,
            WebkitTextStroke: `0.5px ${outline}`,
            paintOrder: 'stroke fill',
          }}
        >
          WORD
        </span>
        <span
          className="text-[7px] font-bold"
          style={{
            color: primary,
            WebkitTextStroke: `0.5px ${outline}`,
            paintOrder: 'stroke fill',
          }}
        >
          TEXT
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Color input — native picker styled for dark theme
// ---------------------------------------------------------------------------

function ColorInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (color: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] text-txt-tertiary">{label}</span>
      <div className="flex items-center gap-2 h-8 px-2 bg-bg-elevated border border-border rounded">
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-5 h-5 rounded-sm border-0 cursor-pointer bg-transparent p-0
            [&::-webkit-color-swatch-wrapper]:p-0
            [&::-webkit-color-swatch]:rounded-sm [&::-webkit-color-swatch]:border-border"
        />
        <span className="text-xs text-txt-secondary font-mono uppercase">
          {value}
        </span>
      </div>
    </div>
  );
}

export { CaptionStyleEditor };
export type { CaptionStyleEditorProps };
