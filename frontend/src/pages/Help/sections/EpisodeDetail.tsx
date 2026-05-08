import {
  FileText,
  ChevronRight,
  Music,
  Scissors,
  Layers,
  Star,
  Clock,
} from 'lucide-react';
import { SectionHeading, SubHeading, Tip, Warning, CodeBlock } from './_shared';

export function EpisodeDetail() {
  return (
    <section id="episode-detail" className="mb-16 scroll-mt-4">
      <SectionHeading id="episode-detail-heading" icon={FileText} title="Episode Detail" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-5">
        The Episode Detail page is your editing workspace. After generation, every aspect of the episode is
        editable without requiring a full regeneration.
      </p>

      <SubHeading id="script-tab" title="Script Tab" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The Script tab shows the full episode script as a list of scenes. Each scene has four editable fields:
      </p>
      <div className="space-y-2 mb-4">
        {[
          { field: 'Narration', desc: 'The spoken text for this scene. This is what the TTS provider reads aloud. Keep it concise — one clear thought per scene works best.' },
          { field: 'Visual Prompt', desc: 'The image generation prompt sent to ComfyUI. Describe the scene visually. Include style modifiers and negative prompts if needed.' },
          { field: 'Duration', desc: 'Scene duration in seconds. Used during assembly to determine how long the scene visual is shown. Defaults to match the voice audio length.' },
          { field: 'Keywords', desc: 'Comma-separated words that will receive buzzword emphasis in captions. These words will pop to center screen with a glow effect when spoken.' },
        ].map(item => (
          <div key={item.field} className="flex gap-3 p-3 surface rounded">
            <span className="text-xs font-mono font-semibold text-accent w-28 shrink-0 mt-0.5">{item.field}</span>
            <p className="text-sm text-txt-secondary">{item.desc}</p>
          </div>
        ))}
      </div>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        After editing scene narration, you have two options: click <strong className="text-txt-primary">Regenerate Voice</strong> to re-run voice synthesis + all downstream steps (captions, assembly, thumbnail), or <strong className="text-txt-primary">Reassemble</strong> to skip re-generating voice and only redo assembly.
      </p>
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-xs font-semibold text-txt-tertiary uppercase tracking-wider mb-2">Scene Example</p>
        <CodeBlock>{`Scene 3 of 6

Narration:
"Light from the sun looks white, but it's actually made
of all the colors of the rainbow mixed together."

Visual Prompt:
"A beam of white sunlight passing through a glass prism,
splitting into a vibrant rainbow spectrum. Clean studio
background. Photorealistic. Sharp focus."

Duration: 8s

Keywords: rainbow, sunlight, prism`}</CodeBlock>
      </div>

      <SubHeading id="scenes-tab" title="Scenes Tab" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The Scenes tab provides a visual grid of all scene images/videos. From here you can:
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">Regenerate a scene</strong> — click the regenerate button on any scene to re-run ComfyUI for that scene only, then automatically reassemble the final video. Useful when one image looks wrong.</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">Edit the visual prompt</strong> — modify the prompt for a scene and click Regenerate Scene to get a new image.</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">Delete a scene</strong> — removes the scene from the script. Remaining scenes are automatically renumbered.</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">Reorder scenes</strong> — drag to reorder or use the reorder endpoint. The new order is saved and reflected in the next assembly.</span></li>
      </ul>
      <Tip>
        If you only want to change the visual for one scene without affecting the audio, edit its visual prompt and click Regenerate Scene. This re-runs just that one ComfyUI job and then reassembles — typically 2–4 minutes.
      </Tip>

      <SubHeading id="captions-tab" title="Captions Tab" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Drevalis Creator Studio includes five built-in caption style presets. Captions are generated from word-level
        timestamps produced by faster-whisper and rendered as an ASS subtitle overlay burned into the video.
      </p>
      <div className="space-y-3 mb-4">
        {[
          {
            id: 'youtube_highlight',
            name: 'YouTube Highlight',
            color: '#FBBF24',
            desc: 'All words in the current line are visible at once. The active (currently spoken) word is highlighted in gold/amber. Large Impact-style font. The most popular style for educational Shorts.',
          },
          {
            id: 'karaoke',
            name: 'Karaoke',
            color: '#60A5FA',
            desc: 'One word appears at a time with a smooth fade transition. Clean and minimal. Works well for slower, deliberate narration where each word should land.',
          },
          {
            id: 'tiktok_pop',
            name: 'TikTok Pop',
            color: '#F472B6',
            desc: 'Words pop in with a scale animation — starting large and snapping to size. High energy. Works well for fast-paced content and hooks.',
          },
          {
            id: 'minimal',
            name: 'Minimal',
            color: '#9898A0',
            desc: 'Small, clean text with no outline or shadow. Subtle and unobtrusive. Best for content where the visual should dominate and captions are secondary.',
          },
          {
            id: 'classic',
            name: 'Classic',
            color: '#EDEDEF',
            desc: 'White text with a solid black outline. Timeless, highly readable against any background. Similar to traditional movie subtitles.',
          },
        ].map(style => (
          <div key={style.id} className="flex gap-3 p-3 surface rounded-lg">
            <div className="w-1 rounded-full shrink-0" style={{ backgroundColor: style.color }} />
            <div>
              <div className="flex items-center gap-2 mb-1">
                <code className="text-xs font-mono text-txt-tertiary">{style.id}</code>
                <span className="text-sm font-medium text-txt-primary">— {style.name}</span>
              </div>
              <p className="text-xs text-txt-secondary leading-relaxed">{style.desc}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        <strong className="text-txt-primary">Buzzword Effects:</strong> If you add keywords to a scene,
        those words will trigger a special overlay animation when spoken — the word "pops" to the center of
        the screen in a large, glowing style, then fades back. This is separate from the line caption and
        adds emphasis to key terms.
      </p>
      <Warning>
        After changing caption style, you must click Reassemble (not just save) for the new style to appear in the video. The caption file is regenerated as part of the assembly step.
      </Warning>

      <SubHeading id="music-tab" title="Music Tab" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The Music tab lets you add background music to an episode. Drevalis Creator Studio supports two music sources:
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><Music size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">AceStep AI Generation</strong> — generates a custom music track tuned to your selected mood. Requires AceStep models installed in ComfyUI. Click Generate Music and wait 60–180 seconds.</span></li>
        <li className="flex gap-2"><Music size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">Curated Library</strong> — a collection of royalty-free music organized by mood. Available immediately without GPU generation.</span></li>
      </ul>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Controls: <strong className="text-txt-primary">Music Volume</strong> sets the background music level (0–100%). When sidechain ducking is enabled (recommended), the music automatically lowers when the narrator speaks and rises during pauses, keeping dialogue clearly audible.
      </p>
      <Tip>
        Set music volume to 20–35% with sidechain ducking enabled for the most natural-sounding mix. Higher volumes can overwhelm the narration.
      </Tip>

      <SubHeading id="video-editor" title="Video Editor" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The Video Editor tab provides post-processing controls applied during the final assembly step:
      </p>
      <div className="grid grid-cols-2 gap-3 mb-4">
        {[
          { icon: Scissors, name: 'Trim', desc: 'Set in/out points to trim the beginning and/or end of the final video.' },
          { icon: Layers, name: 'Borders', desc: 'Add colored border/frame overlays. Useful for brand consistency across episodes.' },
          { icon: Star, name: 'Color Filters', desc: 'Apply LUT-based color grading presets (warm, cool, cinematic, etc.).' },
          { icon: Clock, name: 'Speed', desc: 'Adjust playback speed (0.5x to 2x). Audio is pitch-corrected automatically.' },
        ].map(item => (
          <div key={item.name} className="surface p-3 rounded-lg flex gap-2">
            <item.icon size={14} className="text-accent shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-txt-primary mb-0.5">{item.name}</p>
              <p className="text-xs text-txt-secondary">{item.desc}</p>
            </div>
          </div>
        ))}
      </div>

      <SubHeading id="per-episode-settings" title="Per-Episode Settings" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Each episode can override the series defaults for:
      </p>
      <ul className="space-y-1.5 text-sm text-txt-secondary ml-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">Voice Profile</strong> — use a different voice for this episode without changing the series default</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">Caption Style</strong> — override the caption preset for this specific episode</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">ComfyUI Workflow</strong> — use a different image/video generation workflow</span></li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><span><strong className="text-txt-primary">LLM Config</strong> — use a different model for script regeneration</span></li>
      </ul>
    </section>
  );
}

export default EpisodeDetail;
