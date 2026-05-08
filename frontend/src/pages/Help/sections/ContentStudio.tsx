import { Film, Image, Play } from 'lucide-react';
import {
  SectionHeading,
  SubHeading,
  Tip,
  Warning,
  InfoBox,
  CodeBlock,
  StepBadge,
} from './_shared';

export function ContentStudio() {
  return (
    <section id="content-studio" className="mb-16 scroll-mt-4">
      <SectionHeading id="content-studio-heading" icon={Film} title="Content Studio" />

      <SubHeading id="series" title="Series" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        A <strong className="text-txt-primary">Series</strong> is the top-level container for your content.
        It holds a <em>series bible</em> — a description of the show's tone, target audience, and content rules
        — along with default settings for voice, visual style, LLM, and ComfyUI workflow. Every episode in a
        series inherits these defaults but can override them individually.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Think of a series as a show template. When the LLM writes episode scripts, it receives the series bible
        as context, which ensures all episodes maintain consistent tone, vocabulary, and structure.
      </p>
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-xs font-semibold text-txt-tertiary uppercase tracking-wider mb-2">Series Bible Example</p>
        <CodeBlock>{`Name: Fun Science Facts for Kids

Bible:
"Short, engaging science explainers for ages 8-14.
Each episode covers one fascinating science topic in under
60 seconds. Use simple analogies and avoid jargon. Always
end with a surprising 'mind-blowing' fact. Friendly,
curious tone — like a knowledgeable older sibling."

Visual Style: Bright, colorful illustrations. No real photos.
Episode Length: 45-55 seconds
Voice: Energetic female narrator`}</CodeBlock>
      </div>
      <Tip>
        Write a detailed series bible — the more context you give the LLM, the more consistent and on-brand your episodes will be. Include tone, vocabulary level, structure, and what to avoid.
      </Tip>

      <SubHeading id="episodes" title="Episodes & The 6-Step Pipeline" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-4">
        When you click <strong className="text-txt-primary">Generate</strong> on an episode, Drevalis Creator Studio
        runs a six-step pipeline as a single background job. Each step is tracked independently — if the job
        fails or is cancelled mid-run, completed steps are automatically skipped on retry.
      </p>
      <div className="space-y-3 mb-4">
        {[
          {
            step: 'Script',
            color: '#818CF8',
            desc: 'The LLM reads your episode topic and series bible, then generates a structured JSON script. The script contains individual scenes, each with narration text, a visual prompt for image generation, duration in seconds, and optional keywords for caption emphasis.',
          },
          {
            step: 'Voice',
            color: '#F472B6',
            desc: "The TTS provider converts each scene's narration text to speech audio. Piper and Kokoro run locally via ONNX models. Edge TTS uses Microsoft's free cloud service. ElevenLabs uses their REST API for premium voices. Audio is saved per scene.",
          },
          {
            step: 'Scenes',
            color: '#34D399',
            desc: "ComfyUI generates a visual asset for each scene using the scene's visual_prompt field. In Image mode, it generates a still image (e.g. via DreamShaper). In Video mode, it generates an animated clip (e.g. via Wan 2.2). Multiple ComfyUI servers can be used in parallel.",
          },
          {
            step: 'Captions',
            color: '#FBBF24',
            desc: 'faster-whisper transcribes the generated voice audio at word-level precision. The transcript is converted to an ASS subtitle file using your chosen caption style preset (font, color, animation). Buzzwords from the script are optionally highlighted with pop-out effects.',
          },
          {
            step: 'Assembly',
            color: '#60A5FA',
            desc: 'FFmpeg composites all elements into the final 9:16 MP4. It combines scene visuals (with Ken Burns pan/zoom for images), voice audio, optional background music (with sidechain ducking), and burned-in caption overlays. Output resolution: 1080x1920 @ 30fps.',
          },
          {
            step: 'Thumbnail',
            color: '#A78BFA',
            desc: 'FFmpeg extracts a representative frame from the final video and applies the series thumbnail style to produce a 1280x720 JPEG. The thumbnail is used as the cover image for YouTube uploads.',
          },
        ].map(item => (
          <div key={item.step} className="flex gap-3 p-3 surface rounded-lg">
            <StepBadge step={item.step} color={item.color} />
            <p className="text-sm text-txt-secondary leading-relaxed">{item.desc}</p>
          </div>
        ))}
      </div>
      <InfoBox>
        You can retry any individual failed step from the Episode Detail page (Retry Step dropdown) or from the Jobs page. Completed steps are never re-run unless you explicitly trigger a full regeneration.
      </InfoBox>

      <SubHeading id="ai-generation" title="AI Generation" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The <strong className="text-txt-primary">AI Generate</strong> button on the Series list page lets you
        create an entire series — including the series bible, default settings, and a set of episode topics —
        from a single text prompt. The LLM generates the full configuration in one request.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Similarly, individual episodes can be generated from a topic alone. The LLM receives your topic, the
        series bible, and example episode structures to produce a fully formatted JSON script ready for the
        voice step.
      </p>
      <CodeBlock>{`AI Generate prompt example:
"A YouTube Shorts series about unsolved historical mysteries.
5 episodes. Target audience: history buffs aged 25-40.
Tone: investigative, slightly dramatic. Each episode covers
one mystery in under 60 seconds."`}</CodeBlock>
      <p className="text-sm text-txt-secondary leading-relaxed mt-3">
        This produces a complete series configuration with name, bible, visual style description, and 5
        episode topics — ready to generate immediately.
      </p>

      <SubHeading id="scene-modes" title="Scene Modes: Image vs Video" />
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="surface p-4 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <Image size={15} className="text-step-scenes" />
            <span className="text-sm font-semibold text-txt-primary">Image Mode</span>
          </div>
          <p className="text-xs text-txt-secondary leading-relaxed mb-3">
            ComfyUI generates one static image per scene. FFmpeg applies a Ken Burns pan/zoom effect (random
            direction per scene) to add motion. Fast to generate — a typical 6-scene Short takes 2–5 minutes
            on a mid-range GPU.
          </p>
          <p className="text-xs text-txt-tertiary">Best for: Quick content, high volume, any GPU</p>
        </div>
        <div className="surface p-4 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <Play size={15} className="text-step-assembly" />
            <span className="text-sm font-semibold text-txt-primary">Video Mode</span>
          </div>
          <p className="text-xs text-txt-secondary leading-relaxed mb-3">
            ComfyUI generates an animated video clip per scene (requires a video generation model like
            Wan 2.2). Clips are visually richer but generation is significantly slower — 10–30+ minutes
            per clip depending on GPU.
          </p>
          <p className="text-xs text-txt-tertiary">Best for: High-quality hero content, powerful GPU</p>
        </div>
      </div>
      <Warning>
        Video mode requires the Wan 2.2 (or equivalent) ComfyUI workflow and compatible models installed in ComfyUI. The job timeout is set to 2 hours to accommodate slow GPU inference.
      </Warning>

      <SubHeading id="walkthrough" title='Example: Creating a "Fun Science Facts" Series' />
      <div className="space-y-4 text-sm text-txt-secondary leading-relaxed">
        <p><strong className="text-txt-primary">1. Create the series.</strong> Go to Series → New Series. Name it "Fun Science Facts". In the Series Bible field, write: <em>"Short, engaging science explainers for kids aged 10-14. Each episode answers one question in under 55 seconds. Use the Feynman technique — explain complex ideas simply. End every episode with a surprising fact."</em></p>
        <p><strong className="text-txt-primary">2. Set defaults.</strong> Choose your voice profile (e.g. Edge TTS "en-US-AriaNeural"), set scene mode to Image, select your DreamShaper ComfyUI workflow, set caption style to "youtube_highlight".</p>
        <p><strong className="text-txt-primary">3. Add episodes.</strong> Add topics: "Why is the sky blue?", "How do planes fly?", "What is DNA?", "Why do we dream?", "How does WiFi work?"</p>
        <p><strong className="text-txt-primary">4. Generate.</strong> Click Generate on the first episode. Watch the Activity Monitor. In 5–8 minutes you'll have a finished 9:16 Short with animated captions, voice narration, and AI-generated scene illustrations.</p>
        <p><strong className="text-txt-primary">5. Review and upload.</strong> Open the episode, play the video, make any edits, then Export → Upload to YouTube. The title and description are pre-filled from the script.</p>
      </div>
    </section>
  );
}

export default ContentStudio;
