import { Mic, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Tip, InfoBox, CodeBlock } from './_shared';

export function TextToVoice() {
  return (
    <section id="text-to-voice" className="mb-16 scroll-mt-4">
      <SectionHeading id="text-to-voice-heading" icon={Mic} title="Text to Voice (Content Studio)" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-5">
        The Text to Voice studio converts any long-form text into narrated audio or video content. It supports
        single-voice narration, multi-character dialogue, chapters, background music, and multiple output
        formats.
      </p>

      <SubHeading id="single-voice" title="Single Voice Narration" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The simplest mode. Paste your text, select a voice profile, and click Generate. The entire text is
        read aloud by a single narrator. Ideal for:
      </p>
      <ul className="space-y-1.5 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" />Faceless YouTube videos with AI narration</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" />Article-to-audio conversion</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" />Simple audiobook generation</li>
      </ul>

      <SubHeading id="multi-voice" title="Multi-Voice with Speaker Tags" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Add <code className="font-mono text-accent text-xs">[Speaker Name]</code> tags at the start of lines
        to assign different voices to different characters. Each tag switches the active voice for all
        following lines until the next tag.
      </p>
      <CodeBlock>{`[Narrator] The door opened slowly, revealing the old library.
A dusty smell filled the room.

[Alice] Who's there? I can hear you breathing.

[Bob] It's me — your old friend from the academy.
      I haven't seen you in fifteen years.

[Alice] Fifteen years... I'd almost given up hope.

[Narrator] She stepped forward, her hand trembling
as she reached for the lamp.`}</CodeBlock>
      <p className="text-sm text-txt-secondary leading-relaxed mt-3 mb-3">
        After writing your script, map each speaker tag to a voice profile. Characters without a mapping
        use the default voice. Voice assignments are saved per audiobook and can be changed and re-generated.
      </p>
      <Tip>
        Use distinct voice profiles for each character — different gender, accent, or speaking speed. This makes dialogue far easier to follow, especially in longer pieces.
      </Tip>

      <SubHeading id="chapters" title="Chapter Support" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Add chapter markers using Markdown H2 headers. Chapters are detected automatically and appear as
        navigation points in the output. This is especially useful for long audiobooks.
      </p>
      <CodeBlock>{`## Chapter 1: The Arrival

[Narrator] The train pulled into the station at exactly midnight.

## Chapter 2: The Discovery

[Alice] I found something in the basement. Come quickly.

## Chapter 3: Revelations

[Narrator] What she had found would change everything.`}</CodeBlock>
      <p className="text-sm text-txt-secondary leading-relaxed mt-3">
        Each chapter can be previewed, edited, and regenerated individually from the audiobook detail page —
        no need to regenerate the entire audiobook to fix one chapter.
      </p>

      <SubHeading id="output-formats" title="Output Formats" />
      <div className="space-y-3 mb-4">
        {[
          {
            format: 'audio_only',
            desc: 'Generates a WAV master file and an MP3 for distribution. No video. Best for podcast episodes and audio-only platforms.',
          },
          {
            format: 'audio_image',
            desc: 'Generates an MP4 video with the cover image displayed statically while audio plays. Standard for YouTube audiobook uploads. Can be portrait (9:16) or landscape (16:9).',
          },
          {
            format: 'audio_video',
            desc: 'Generates an MP4 video with a dark animated background while audio plays. More visually engaging than a static image. Supports caption overlay.',
          },
        ].map(item => (
          <div key={item.format} className="flex gap-3 p-3 surface rounded">
            <code className="text-xs font-mono text-accent shrink-0 mt-0.5">{item.format}</code>
            <p className="text-sm text-txt-secondary leading-relaxed">{item.desc}</p>
          </div>
        ))}
      </div>

      <SubHeading id="audiobook-captions" title="Caption Styles for Audiobooks" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        All five caption styles available for Shorts (youtube_highlight, karaoke, tiktok_pop, minimal,
        classic) are also available for audiobook videos. Captions are generated from the same word-level
        faster-whisper transcription pipeline. Enable captions in the audiobook settings before generating.
      </p>
      <InfoBox>
        Orientation matters for caption legibility. Portrait (9:16) captions are centered with larger font for mobile viewing. Landscape (16:9) uses a wider layout optimized for desktop/TV.
      </InfoBox>
    </section>
  );
}

export default TextToVoice;
