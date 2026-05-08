import {
  Sparkles,
  Film,
  Mic,
  Server,
  Monitor,
  HardDrive,
  Zap,
  CheckSquare,
} from 'lucide-react';
import { SectionHeading, SubHeading, InfoBox } from './_shared';

export function GettingStarted() {
  return (
    <section id="getting-started" className="mb-16 scroll-mt-4">
      <SectionHeading id="getting-started-heading" icon={Sparkles} title="Getting Started" />

      <SubHeading id="what-is" title="What is Drevalis Creator Studio" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Drevalis Creator Studio is a local-first AI-powered video creation studio built for YouTube Shorts and
        long-form text-to-speech content. It automates the entire production pipeline — from generating
        scripts with an LLM, synthesizing voiceovers with TTS, generating scene visuals with ComfyUI,
        adding animated captions, compositing the final video with FFmpeg, and uploading directly to YouTube.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        All heavy processing (LLM inference, TTS synthesis, image/video generation) runs on your local
        machine by default. Cloud providers (Claude AI, ElevenLabs, Edge TTS) are available as opt-in
        alternatives for each component.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed">
        Drevalis Creator Studio handles two primary workflows:
      </p>
      <ul className="mt-3 space-y-2 text-sm text-txt-secondary ml-4">
        <li className="flex gap-2">
          <Film size={14} className="text-accent shrink-0 mt-0.5" />
          <span><strong className="text-txt-primary">YouTube Shorts Studio</strong> — episodic series with AI scripts, TTS narration, ComfyUI scene images or videos, animated word-level captions, and direct upload.</span>
        </li>
        <li className="flex gap-2">
          <Mic size={14} className="text-accent shrink-0 mt-0.5" />
          <span><strong className="text-txt-primary">Text-to-Voice Studio</strong> — converts long-form text into narrated audiobooks or faceless videos with chapter detection, multi-voice dialogue, background music, and multiple output formats.</span>
        </li>
      </ul>

      <SubHeading id="system-requirements" title="System Requirements" />
      <div className="grid grid-cols-2 gap-3 mb-4">
        {[
          {
            icon: Server,
            name: 'ComfyUI',
            desc: 'Required for scene image and video generation. Run locally on GPU or connect to a remote server.',
            status: 'Required for image/video',
          },
          {
            icon: Monitor,
            name: 'FFmpeg',
            desc: 'Required for all video assembly, caption burning, and audio mixing. Must be on your system PATH.',
            status: 'Required',
          },
          {
            icon: HardDrive,
            name: 'PostgreSQL 16',
            desc: 'Stores series, episodes, voice profiles, and job state. Run via Docker or install locally.',
            status: 'Required',
          },
          {
            icon: Zap,
            name: 'Redis',
            desc: 'Powers the arq job queue and real-time progress via pub/sub. Run via Docker or install locally.',
            status: 'Required',
          },
        ].map(item => (
          <div key={item.name} className="surface p-3 rounded-lg">
            <div className="flex items-center gap-2 mb-1">
              <item.icon size={14} className="text-accent" />
              <span className="text-sm font-medium text-txt-primary">{item.name}</span>
              <span className="ml-auto text-xs text-txt-tertiary">{item.status}</span>
            </div>
            <p className="text-xs text-txt-secondary leading-relaxed">{item.desc}</p>
          </div>
        ))}
      </div>
      <InfoBox>
        The fastest way to start all infrastructure is <code className="font-mono text-accent">docker compose up -d</code>. This starts PostgreSQL, Redis, the backend API, the arq worker, and the frontend in one command.
      </InfoBox>

      <SubHeading id="setup-checklist" title="First-Time Setup Checklist" />
      <div className="space-y-2 mb-4">
        {[
          'Docker running — start infrastructure with docker compose up -d',
          'Open http://localhost:5173 in your browser',
          'Go to Settings → ComfyUI — add your ComfyUI server URL and test the connection',
          'Go to Settings → LLM — configure your LM Studio or OpenAI-compatible endpoint',
          'Go to Settings → Voice Profiles — create at least one voice profile (Edge TTS has 17+ free voices)',
          'Optional: Settings → YouTube — connect your Google account for direct uploads',
          'Optional: Configure ElevenLabs API key in a voice profile for premium voices',
          'Create your first Series and generate an episode',
        ].map((item, i) => (
          <div key={i} className="flex items-start gap-3 text-sm text-txt-secondary">
            <CheckSquare size={14} className="text-success shrink-0 mt-0.5" />
            <span>{item}</span>
          </div>
        ))}
      </div>

      <SubHeading id="quick-start" title="Quick Start: Your First Video in 5 Steps" />
      <div className="space-y-4">
        {[
          {
            step: '1',
            title: 'Configure Services',
            desc: 'Navigate to Settings. Add a ComfyUI server (usually http://localhost:8188) and test the connection. Set up your LLM endpoint (LM Studio default: http://localhost:1234/v1). Create a voice profile using Edge TTS — pick any voice from the dropdown and click Preview to hear it.',
          },
          {
            step: '2',
            title: 'Create a Series',
            desc: 'Go to Series → New Series. Give it a name like "Fun Science Facts", write a short series bible describing the tone and content style, select your voice profile and ComfyUI workflow, then save. Alternatively, click AI Generate — type a one-sentence idea and the LLM will create the series config and 5 episode topics automatically.',
          },
          {
            step: '3',
            title: 'Add an Episode',
            desc: 'Inside your series, click New Episode. Add a topic like "Why is the sky blue?" and save. You can also bulk-add topics from the series detail page.',
          },
          {
            step: '4',
            title: 'Generate',
            desc: 'Click the Generate button on the episode. Watch the Activity Monitor in the bottom-right corner — it shows real-time progress through all 6 pipeline steps: Script → Voice → Scenes → Captions → Assembly → Thumbnail. Generation time depends on your GPU. An image-mode Short typically takes 3–8 minutes.',
          },
          {
            step: '5',
            title: 'Review and Export',
            desc: 'Open the finished episode. Play the video. Edit any scene narration or visual prompts if needed, then click Reassemble to rebuild with your changes. When satisfied, use the Export menu to download the MP4 bundle or Upload to YouTube directly from the app.',
          },
        ].map(item => (
          <div key={item.step} className="flex gap-4">
            <div className="w-8 h-8 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center shrink-0 text-sm font-bold text-accent">
              {item.step}
            </div>
            <div>
              <p className="text-sm font-semibold text-txt-primary mb-1">{item.title}</p>
              <p className="text-sm text-txt-secondary leading-relaxed">{item.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default GettingStarted;
