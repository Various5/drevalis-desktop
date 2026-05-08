import { Layers, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Tip, InfoBox } from './_shared';

export function LoadBalancing() {
  return (
    <section id="load-balancing" className="mb-16 scroll-mt-4">
      <SectionHeading id="load-balancing-heading" icon={Layers} title="Load Balancing" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-5">
        Drevalis Creator Studio can distribute work across multiple ComfyUI servers and LLM endpoints. This is
        useful when you have several machines with GPUs, or when you want to separate image generation
        from video generation onto different hardware.
      </p>

      <SubHeading id="lb-comfyui" title="Registering Multiple ComfyUI Servers" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Go to Settings → ComfyUI Servers → Add Server. Register as many servers as you have available.
        Each server entry includes:
      </p>
      <ul className="space-y-1.5 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">URL</strong> — the server address (e.g. <code className="font-mono text-xs text-accent">http://192.168.1.50:8188</code>)</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Max Concurrent Jobs</strong> — how many ComfyUI workflows this server can run simultaneously. Set based on your GPU's VRAM capacity.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Active toggle</strong> — take a server offline temporarily without deleting it (useful for maintenance).</li>
      </ul>
      <Tip>
        For a typical two-GPU setup: register both servers with Max Concurrent Jobs = 1 each. Both will be used in parallel when generating a multi-scene episode — each scene goes to whichever server is free first.
      </Tip>

      <SubHeading id="lb-llm" title="Registering Multiple LLM Configs" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Multiple LLM configs can be registered (Settings → LLM Configs → Add Config). Each config can
        point to a different server or model. Series and episodes select which LLM config to use — you
        can run fast script generation for Shorts on a small local model while long-form documentaries
        use a larger, slower model for higher quality output.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Unlike ComfyUI servers, LLM configs are not pooled automatically — you select the config per
        series. However, multiple arq worker jobs running simultaneously will each make independent
        requests to their assigned LLM endpoint in parallel.
      </p>

      <SubHeading id="lb-distribution" title="How Distribution Works" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        ComfyUI server selection uses a <strong className="text-txt-primary">least-loaded acquisition strategy</strong>:
      </p>
      <div className="surface p-4 rounded-lg mb-4">
        <ol className="list-decimal list-inside space-y-2 text-sm text-txt-secondary ml-1">
          <li>When a scene needs to be generated, the server pool checks all active servers.</li>
          <li>Each server has a semaphore tracking its current job count vs. its <code className="font-mono text-xs text-accent">max_concurrent_jobs</code> limit.</li>
          <li>The server with the most available slots (i.e. fewest active jobs relative to its limit) is selected.</li>
          <li>If all servers are at capacity, the scene request waits until a slot opens.</li>
          <li>The scene job is sent to the selected server via the ComfyUI WebSocket API and polled for completion.</li>
        </ol>
      </div>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        For a typical episode with 6 scenes and 2 ComfyUI servers (each with <code className="font-mono text-xs text-accent">max_concurrent_jobs=1</code>),
        scenes are processed two at a time in parallel, roughly halving total scene generation time.
      </p>
      <InfoBox>
        All registered servers must have the required ComfyUI workflows and model weights installed. A workflow registered for one server will fail on another server that doesn't have the same models. Check Settings → ComfyUI → Test Connection to verify each server individually.
      </InfoBox>
    </section>
  );
}

export default LoadBalancing;
