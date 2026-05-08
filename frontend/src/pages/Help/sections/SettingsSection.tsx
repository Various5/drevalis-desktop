import { Settings, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, InfoBox } from './_shared';

export function SettingsSection() {
  return (
    <section id="settings" className="mb-16 scroll-mt-4">
      <SectionHeading id="settings-heading" icon={Settings} title="Settings" />

      <SubHeading id="comfyui-settings" title="ComfyUI Servers" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Drevalis Creator Studio supports multiple ComfyUI servers for parallel scene generation. Add servers in
        Settings → ComfyUI Servers. Each server has:
      </p>
      <ul className="space-y-1.5 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">URL</strong> — the ComfyUI server address (e.g. http://localhost:8188)</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">API Key</strong> — optional, if your ComfyUI instance is protected</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Max Concurrent Jobs</strong> — how many parallel workflow runs this server can handle</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Active/Inactive toggle</strong> — quickly disable a server without deleting it</li>
      </ul>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Click <strong className="text-txt-primary">Test Connection</strong> to verify the server is reachable
        and the API key is valid. The server pool uses a least-loaded acquisition strategy — scenes are
        routed to whichever server has the fewest active jobs.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        <strong className="text-txt-primary">Workflows</strong> define how images and videos are generated.
        Each workflow is a ComfyUI workflow JSON with input mappings that tell Drevalis Creator Studio which node IDs
        correspond to the prompt, seed, dimensions, and other parameters.
      </p>

      <SubHeading id="llm-settings" title="LLM Configs" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        LLM configs define the AI model used for script generation. Supported providers:
      </p>
      <div className="space-y-2 mb-4">
        {[
          { name: 'LM Studio', desc: 'Local LLM inference. Default URL: http://localhost:1234/v1. Works with any model loaded in LM Studio. The OpenAI-compatible API is used.' },
          { name: 'Ollama', desc: 'Local LLM via Ollama. Point the base URL to your Ollama server (e.g. http://localhost:11434/v1).' },
          { name: 'OpenAI', desc: 'OpenAI API. Enter your API key and select a model (gpt-4o, gpt-4o-mini, etc.).' },
          { name: 'Anthropic (Claude)', desc: 'Set the ANTHROPIC_API_KEY environment variable. Supports Claude 3.5 Sonnet, Claude 3 Haiku, and other Anthropic models.' },
        ].map(item => (
          <div key={item.name} className="flex gap-3 p-3 surface rounded">
            <span className="text-xs font-mono font-semibold text-accent shrink-0 w-24 mt-0.5">{item.name}</span>
            <p className="text-sm text-txt-secondary">{item.desc}</p>
          </div>
        ))}
      </div>
      <p className="text-sm text-txt-secondary leading-relaxed">
        Use <strong className="text-txt-primary">Test Connection</strong> to verify the LLM config works —
        it sends a minimal prompt and reports the response time and model name.
      </p>

      <SubHeading id="storage-settings" title="Storage" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Settings → Storage shows current disk usage broken down by category: episodes, audiobooks,
        voice previews, and models. All files are stored in the <code className="font-mono text-accent text-xs">storage/</code>
        directory relative to <code className="font-mono text-accent text-xs">STORAGE_BASE_PATH</code>.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed">
        Scene images and video clips are the largest storage consumers. A typical 6-scene Short uses
        50–200MB during generation (including temp files) and 10–30MB for the final MP4 output.
      </p>

      <SubHeading id="ffmpeg-settings" title="FFmpeg" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Settings → FFmpeg shows the detected FFmpeg version, path, and supported codecs. If FFmpeg is
        not detected, verify it is installed and available on your system PATH.
      </p>
      <InfoBox>
        Drevalis Creator Studio requires FFmpeg with libx264, libopus, and libmp3lame support. Most standard FFmpeg builds include these. The output codec is H.264 High profile with yuv420p pixel format for maximum browser compatibility.
      </InfoBox>
    </section>
  );
}

export default SettingsSection;
