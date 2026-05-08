import { Film, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Tip, InfoBox } from './_shared';

export function LongformVideos() {
  return (
    <section id="longform-videos" className="mb-16 scroll-mt-4">
      <SectionHeading id="longform-videos-heading" icon={Film} title="Long-Form Videos" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-5">
        In addition to 60-second Shorts, Drevalis Creator Studio supports documentary-style long-form videos
        ranging from 15 minutes to over an hour. Long-form videos use the same pipeline but with
        chapter-aware assembly, per-chapter music, and 16:9 landscape output.
      </p>

      <SubHeading id="longform-overview" title="Overview & Content Format Toggle" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Each series has a <strong className="text-txt-primary">Content Format</strong> setting that controls
        the output type. Switching from <code className="font-mono text-accent text-xs">shorts</code> to{' '}
        <code className="font-mono text-accent text-xs">longform</code> changes several defaults:
      </p>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="surface p-4 rounded-lg">
          <p className="text-xs font-semibold text-txt-tertiary uppercase tracking-wider mb-2">Shorts Mode</p>
          <ul className="space-y-1.5 text-xs text-txt-secondary">
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />9:16 portrait (1080×1920)</li>
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />Up to 60 seconds</li>
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />Single music track</li>
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />6 pipeline steps</li>
          </ul>
        </div>
        <div className="surface p-4 rounded-lg">
          <p className="text-xs font-semibold text-txt-tertiary uppercase tracking-wider mb-2">Long-Form Mode</p>
          <ul className="space-y-1.5 text-xs text-txt-secondary">
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />16:9 landscape (1920×1080)</li>
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />15–60+ minutes</li>
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />Per-chapter background music</li>
            <li className="flex gap-2"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />Chapter-aware assembly</li>
          </ul>
        </div>
      </div>

      <SubHeading id="longform-series" title="Creating a Long-Form Series" />
      <div className="space-y-3 text-sm text-txt-secondary leading-relaxed mb-4">
        <p><strong className="text-txt-primary">1.</strong> Go to Series → New Series.</p>
        <p><strong className="text-txt-primary">2.</strong> Set <strong className="text-txt-primary">Content Format</strong> to <code className="font-mono text-accent text-xs">longform</code>.</p>
        <p><strong className="text-txt-primary">3.</strong> Set <strong className="text-txt-primary">Scenes Per Chapter</strong> — how many visual scenes the LLM generates per chapter (typically 4–8). More scenes means more visual variety but longer generation time.</p>
        <p><strong className="text-txt-primary">4.</strong> Write a series bible that describes the documentary style, chapter structure, and narration tone.</p>
        <p><strong className="text-txt-primary">5.</strong> Optionally add a <strong className="text-txt-primary">Visual Consistency Prompt</strong> — a shared style fragment appended to every scene's image prompt to keep the visual aesthetic coherent across all chapters (e.g. "cinematic 16mm film grain, warm color grading, shallow depth of field").</p>
      </div>
      <Tip>
        For long-form videos, use Wan 2.2 video clips (Video Mode) rather than static images. The motion adds production value that justifies longer watch time. Expect 45–90 minutes of total generation time on a mid-range GPU.
      </Tip>

      <SubHeading id="longform-chapters" title="Chapter-Aware Assembly" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Long-form episodes are structured as a list of chapters, each with its own scenes, narration,
        and optional music mood. Assembly is chapter-aware: each chapter is composited independently
        first, then joined in sequence. This means:
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span>Each chapter can have a <strong className="text-txt-primary">different music mood</strong> — e.g. "calm" for the introduction, "epic" for the climax, "ambient" for the conclusion.</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span>Individual chapters can be <strong className="text-txt-primary">regenerated</strong> without re-running the entire episode.</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span>Chapter titles are embedded as <strong className="text-txt-primary">YouTube chapter markers</strong> in the video description automatically.</span></li>
      </ul>

      <SubHeading id="longform-output" title="16:9 Output & Visual Consistency" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Long-form output is rendered at 1920×1080 (16:9) at 30fps. Caption layout adapts automatically
        to the wider aspect ratio — text is positioned in the lower third rather than centered.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The <strong className="text-txt-primary">Visual Consistency Prompt</strong> (set in series settings)
        is appended to every scene's visual prompt before it is sent to ComfyUI. This keeps the color
        grading, lighting style, and art direction consistent across all scenes regardless of their
        individual content.
      </p>
      <InfoBox>
        Long-form jobs are assigned lower priority than Shorts in the worker queue. Shorts in the same queue will complete first. You can monitor queue position in the Activity Monitor.
      </InfoBox>

      <h3 className="font-display text-sm mt-8 mb-2">Music videos &amp; animation</h3>
      <p className="text-sm text-txt-secondary leading-relaxed mb-4">
        Two additional formats live alongside Shorts and Long-form:
      </p>
      <ul className="text-sm text-txt-secondary leading-relaxed list-disc pl-5 space-y-1.5">
        <li>
          <strong className="text-txt-primary">Music video.</strong> The backing track is the content.
          The LLM writes lyrics, the audio engine renders the full song with vocals, and scenes cut
          to the beats. Works for both 9:16 and 16:9 delivery. Best on a GPU that can run an
          AI-music workflow (ACE Step / similar) — without one the pipeline falls back to library
          music + the standard scene flow, so the episode still ships.
        </li>
        <li>
          <strong className="text-txt-primary">Animation.</strong> Routes every scene through an
          animation-tagged workflow and prepends a style anchor to every prompt — nine presets
          ship: anime classic / modern, Studio Ghibli, Cartoon Network, Pixar 3D, Disney 3D,
          motion comic, stop motion, pixel art. Import an animation workflow once, then pick the
          style from the series settings.
        </li>
      </ul>
      <div className="mt-4"><InfoBox>
        Both music video and animation share the long-form chapter-based pipeline under the hood.
        You get the same chapter structure + cost estimate + assembly hygiene as a regular
        long-form series — the format only changes how prompts and audio are generated.
      </InfoBox></div>
    </section>
  );
}

export default LongformVideos;
