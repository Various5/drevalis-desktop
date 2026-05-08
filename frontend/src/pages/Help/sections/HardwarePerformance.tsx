import { HardDrive, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Tip } from './_shared';

export function HardwarePerformance() {
  return (
    <section id="hardware-performance" className="mb-16 scroll-mt-4">
      <SectionHeading id="hardware-performance-heading" icon={HardDrive} title="Hardware & Performance" />

      <SubHeading id="hw-matrix" title="Hardware Matrix & Expected Times" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Realistic wall-clock times on typical builds. Scene generation dominates - GPU tier moves these numbers most. LLM and TTS steps are fast even on modest CPUs.
      </p>
      <div className="overflow-x-auto mb-4">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-border text-txt-secondary uppercase tracking-wider">
              <th className="text-left py-2 pr-3">Build</th>
              <th className="text-left py-2 pr-3">CPU / RAM</th>
              <th className="text-left py-2 pr-3">GPU</th>
              <th className="text-left py-2 pr-3">60s Short</th>
              <th className="text-left py-2 pr-3">10m long-form</th>
              <th className="text-left py-2 pr-3">30m audiobook</th>
            </tr>
          </thead>
          <tbody className="text-txt-secondary">
            <tr className="border-b border-border/50"><td className="py-2 pr-3"><strong className="text-txt-primary">Entry</strong></td><td className="py-2 pr-3">i5/Ryzen 5 6c, 16 GB</td><td className="py-2 pr-3">RTX 3060 8 GB</td><td className="py-2 pr-3">20-40 min</td><td className="py-2 pr-3">2.5-5 h</td><td className="py-2 pr-3">4-10 min</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-3"><strong className="text-txt-primary">Mid</strong></td><td className="py-2 pr-3">i7/Ryzen 7 8c, 32 GB</td><td className="py-2 pr-3">RTX 4070 12 GB</td><td className="py-2 pr-3">8-15 min</td><td className="py-2 pr-3">45-90 min</td><td className="py-2 pr-3">2-5 min</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-3"><strong className="text-txt-primary">High</strong></td><td className="py-2 pr-3">i9/Ryzen 9 12c+, 64 GB</td><td className="py-2 pr-3">RTX 4090 24 GB</td><td className="py-2 pr-3">3-7 min</td><td className="py-2 pr-3">20-40 min</td><td className="py-2 pr-3">1-3 min</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-3"><strong className="text-txt-primary">Cloud</strong></td><td className="py-2 pr-3">any quad, 16 GB</td><td className="py-2 pr-3">RunPod A100/H100</td><td className="py-2 pr-3">3-8 min</td><td className="py-2 pr-3">30-60 min</td><td className="py-2 pr-3">2-5 min</td></tr>
          </tbody>
        </table>
      </div>

      <SubHeading id="hw-gpu" title="GPU Recommendations" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">8 GB VRAM minimum</strong> for image-only (Qwen Image) scene workflows at 720p. Below this you will OOM on the first scene.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">16 GB VRAM</strong> is the sweet spot - every workflow runs, long-form video (Wan 2.2) fits, caption generation via faster-whisper has headroom.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">24 GB VRAM (RTX 4090 / 3090)</strong> - runs multiple workflows concurrently; you can have ComfyUI + LM Studio both loaded without swapping.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">AMD ROCm</strong> works for ComfyUI but is slower; budget 2x the quoted times.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">No GPU</strong> - use RunPod on Pro/Studio. Episodes cost $0.10-0.50 each in compute depending on tier.</li>
      </ul>

      <SubHeading id="hw-scaling" title="Scaling: Multiple ComfyUI Servers" />
      <p className="text-sm text-txt-secondary mb-3">
        Drevalis parallelizes scene generation across every registered ComfyUI server. With 2 servers you get ~1.8x throughput; with 4 servers ~3.5x. Each server needs its own GPU.
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Add a server:</strong> Settings -&gt; ComfyUI Servers -&gt; Add. Specify URL, optional API key, and max_concurrent_video_jobs.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Round-robin:</strong> scenes are distributed round-robin. Each server has its own semaphore; a slow server doesn't block a fast one.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Concurrency scales:</strong> base is 4; each extra server adds +2 slots up to max_concurrent_generations.</li>
      </ul>
      <Tip>For long-form video, a second GPU dedicated to Wan 2.2 workflows is the single biggest speed-up. Run it on a secondary machine on your LAN.</Tip>

      <SubHeading id="hw-cloud" title="RunPod Cloud GPU (Pro / Studio)" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">A100 40 GB</strong> - ~$1.50/hr, runs all workflows smoothly. Good for bursty workloads.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">H100 80 GB</strong> - ~$3/hr, fastest option. Use for long-form video bursts only.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Stop when done</strong> - Settings -&gt; Cloud GPU -&gt; Stop. Stopped pods don't charge for compute but do for the persistent volume (~$0.05/GB/month).</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Delete when finished</strong> - stopping preserves state; deleting wipes the volume. Delete when you're done with the project to stop all charges.</li>
      </ul>

      <SubHeading id="hw-network" title="Network & Storage" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Disk:</strong> each 60s Short is ~30-50 MB final output + ~500 MB intermediate assets (cleaned up after success). Long-form 10 min can peak at 5 GB intermediate. Reserve 100+ GB for active use; backups can go off-box.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Upload bandwidth:</strong> YouTube/TikTok uploads hit ~50 Mbps each. Scheduling 5 uploads at once will saturate a 200 Mbps link.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">SSD strongly recommended:</strong> HDDs bottleneck the captions step (faster-whisper opens dozens of model weights).</li>
      </ul>
    </section>
  );
}

export default HardwarePerformance;
