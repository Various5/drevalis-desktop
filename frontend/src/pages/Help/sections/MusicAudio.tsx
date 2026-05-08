import { Music, Hash } from 'lucide-react';
import { SectionHeading, SubHeading, Warning } from './_shared';

export function MusicAudio() {
  return (
    <section id="music-audio" className="mb-16 scroll-mt-4">
      <SectionHeading id="music-audio-heading" icon={Music} title="Music & Audio" />

      <SubHeading id="acestep" title="AceStep AI Music Generation" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        AceStep is an AI music generation model that creates royalty-free background music customized to a
        mood prompt. It runs as a ComfyUI workflow — the music generation request is sent to your ComfyUI
        server the same way scene images are generated.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        When you select a mood and click Generate Music, Drevalis Creator Studio sends the mood description to ComfyUI,
        which runs AceStep and returns a WAV audio file. Generation typically takes 60–180 seconds depending
        on output duration and GPU speed.
      </p>
      <Warning>
        AceStep requires the AceStep ComfyUI custom node and model weights installed separately. If music generation fails with a "node not found" error, AceStep is not installed in your ComfyUI.
      </Warning>

      <SubHeading id="mood-presets" title="12 Mood Presets" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-4">
        {[
          { mood: 'epic', desc: 'Orchestral, powerful build-ups. Good for dramatic reveals.' },
          { mood: 'calm', desc: 'Soft, ambient pads. Meditation and relaxation content.' },
          { mood: 'dark', desc: 'Tense, minor key. Mystery and thriller content.' },
          { mood: 'upbeat', desc: 'Positive, energetic. Lifestyle and travel content.' },
          { mood: 'cinematic', desc: 'Film-score style. Emotional storytelling.' },
          { mood: 'lofi', desc: 'Relaxed hip-hop beats. Study and focus content.' },
          { mood: 'ambient', desc: 'Atmospheric textures. Background filler.' },
          { mood: 'corporate', desc: 'Professional, motivational. Business content.' },
          { mood: 'playful', desc: "Light, whimsical. Children's content." },
          { mood: 'suspenseful', desc: 'Building tension. True crime, investigative.' },
          { mood: 'inspiring', desc: 'Uplifting, hopeful. Success stories.' },
          { mood: 'retro', desc: 'Vintage synth vibes. Nostalgic content.' },
        ].map(item => (
          <div key={item.mood} className="surface p-2.5 rounded">
            <p className="text-xs font-mono font-semibold text-accent mb-1">{item.mood}</p>
            <p className="text-xs text-txt-tertiary leading-relaxed">{item.desc}</p>
          </div>
        ))}
      </div>

      <SubHeading id="mastering" title="Audio Mastering Chain" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        When background music is mixed with narration, Drevalis Creator Studio applies an automated mastering chain
        via FFmpeg audio filters. The chain runs during the Assembly step:
      </p>
      <div className="space-y-2 mb-4">
        {[
          { stage: 'Voice EQ', desc: 'High-pass filter (80Hz cut) removes low-end rumble from TTS audio. Slight presence boost around 3kHz for clarity.' },
          { stage: 'Compression', desc: 'Soft-knee compression on the voice track normalizes dynamic range so quiet and loud passages are balanced.' },
          { stage: 'Music Reverb', desc: 'Subtle room reverb on the music track blends it into the same acoustic space as the narration.' },
          { stage: 'Sidechain Ducking', desc: 'Music volume is automatically lowered when the narrator speaks. Restores to full level during pauses.' },
          { stage: 'Final Limiter', desc: 'Hard limiter on the mix output prevents clipping at -1dBFS. Ensures consistent loudness across episodes.' },
        ].map(item => (
          <div key={item.stage} className="flex gap-3 p-3 surface rounded">
            <Hash size={13} className="text-accent shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-txt-primary mb-0.5">{item.stage}</p>
              <p className="text-xs text-txt-secondary leading-relaxed">{item.desc}</p>
            </div>
          </div>
        ))}
      </div>

      <SubHeading id="sidechain" title="Sidechain Ducking Explained Simply" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Sidechain ducking is a professional audio technique used in every podcast and video. The basic idea:
      </p>
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-sm text-txt-secondary leading-relaxed">
          Imagine two audio tracks — the narrator's voice and background music. Without ducking, both play
          at the same volume and the music competes with speech. With sidechain ducking, the music "listens"
          to the voice track. When the narrator starts speaking, the music automatically dips to a lower
          volume. When the narrator pauses (breath, end of sentence), the music rises back up. The result
          sounds natural — like the music is giving way to the voice, then filling the silence again.
        </p>
      </div>
      <p className="text-sm text-txt-secondary leading-relaxed">
        In Drevalis Creator Studio, the ducking ratio is 6dB by default (music drops to ~50% perceived volume when
        voice is present) with a 50ms attack and 500ms release. These values produce natural transitions
        without abrupt pumping.
      </p>
    </section>
  );
}

export default MusicAudio;
