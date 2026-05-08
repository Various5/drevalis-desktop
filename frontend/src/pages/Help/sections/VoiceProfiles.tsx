import { Volume2, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Tip } from './_shared';

export function VoiceProfiles() {
  return (
    <section id="voice-profiles" className="mb-16 scroll-mt-4">
      <SectionHeading id="voice-profiles-heading" icon={Volume2} title="Voice Profiles" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-5">
        A Voice Profile defines a TTS provider, voice model, and audio processing settings. You can create
        as many profiles as you need — one per character, language, or style.
      </p>

      <SubHeading id="providers" title="Supported TTS Providers" />
      <div className="space-y-3 mb-4">
        {[
          {
            name: 'Edge TTS',
            tag: 'Free cloud',
            tagColor: 'success',
            desc: "Microsoft's neural TTS service. No API key required. 17+ voices included (en-US-AriaNeural, en-US-GuyNeural, en-GB-SoniaNeural, en-AU-NatashaNeural, and more). Good quality for most use cases. Requires internet connection.",
            voices: 'en-US-AriaNeural, en-US-GuyNeural, en-US-JennyNeural, en-GB-RyanNeural, en-AU-WilliamNeural',
          },
          {
            name: 'Piper TTS',
            tag: 'Local / Free',
            tagColor: 'info',
            desc: 'Offline ONNX-based TTS. Download voice model files (.onnx + .json) and place them in storage/models/piper/. Completely private — no internet required. Voice quality varies by model.',
            voices: 'en_US-lessac-medium, en_US-ryan-high, en_GB-alan-low',
          },
          {
            name: 'Kokoro TTS',
            tag: 'Local / High Quality',
            tagColor: 'info',
            desc: 'High-quality local ONNX TTS via the kokoro library. Optional dependency (pip install .[kokoro]). Better voice quality than Piper for English. Runs on CPU or GPU.',
            voices: 'af, af_bella, af_sarah, am_adam, bf_emma, bm_george',
          },
          {
            name: 'ElevenLabs',
            tag: 'Premium cloud',
            tagColor: 'warning',
            desc: 'Premium cloud TTS with the most natural-sounding voices. Requires an ElevenLabs API key (set in the voice profile). Costs credits per character generated.',
            voices: 'Roger, Sarah, Laura, Charlie, George, Callum, River, Liam',
          },
        ].map(provider => (
          <div key={provider.name} className="surface p-4 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-semibold text-txt-primary">{provider.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full bg-${provider.tagColor}/10 text-${provider.tagColor}`}>
                {provider.tag}
              </span>
            </div>
            <p className="text-xs text-txt-secondary leading-relaxed mb-2">{provider.desc}</p>
            <p className="text-xs text-txt-tertiary">
              <span className="font-medium text-txt-secondary">Example voices: </span>
              {provider.voices}
            </p>
          </div>
        ))}
      </div>

      <SubHeading id="creating-profile" title="Creating a Voice Profile Step by Step" />
      <div className="space-y-3 text-sm text-txt-secondary leading-relaxed">
        <p><strong className="text-txt-primary">1.</strong> Go to Settings → Voice Profiles → New Profile.</p>
        <p><strong className="text-txt-primary">2.</strong> Enter a name (e.g. "Aria — Energetic Female EN").</p>
        <p><strong className="text-txt-primary">3.</strong> Select Provider: choose Edge TTS, Piper, Kokoro, or ElevenLabs.</p>
        <p><strong className="text-txt-primary">4.</strong> Select Voice: the dropdown populates with available voices for the chosen provider. For ElevenLabs, enter your API key first.</p>
        <p><strong className="text-txt-primary">5.</strong> Adjust Speed (0.5x–2.0x) and Pitch (-20 to +20 semitones) if needed.</p>
        <p><strong className="text-txt-primary">6.</strong> Click Preview to hear a sample phrase read in the selected voice. Iterate until satisfied.</p>
        <p><strong className="text-txt-primary">7.</strong> Save. The profile is now available in all series and episode settings.</p>
      </div>

      <SubHeading id="voice-preview" title="Previewing Voices" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Every voice profile has a Preview button. Clicking it generates a short audio clip using the
        configured voice, speed, and pitch settings. The preview audio plays directly in the browser.
        Preview audio is cached in <code className="font-mono text-accent text-xs">storage/voice_previews/</code>
        so repeated previews are instant.
      </p>

      <SubHeading id="speed-pitch" title="Speed and Pitch Controls" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Speed and pitch are applied post-synthesis using FFmpeg audio filters:
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Speed:</strong> 0.5x (half speed) to 2.0x (double speed). 1.0x is the natural voice speed. Increasing speed reduces total video duration.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Pitch:</strong> -20 to +20 semitones. Positive values raise pitch (higher, lighter voice). Negative values lower pitch (deeper, heavier voice). 0 is no change.</li>
      </ul>
      <Tip>
        Use distinct voice profiles for each character — different gender, accent, or speaking speed. This makes dialogue far easier to follow, especially in longer pieces.
      </Tip>
    </section>
  );
}

export default VoiceProfiles;
