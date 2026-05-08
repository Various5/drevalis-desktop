import { Lightbulb, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading } from './_shared';

export function ProTips() {
  return (
    <section id="pro-tips" className="mb-16 scroll-mt-4">
      <SectionHeading id="pro-tips-heading" icon={Lightbulb} title="Pro Tips" />

      <SubHeading id="tips-quality" title="Getting Better Output Quality" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Series bible over per-episode tuning</strong> - invest 15 minutes writing a detailed series description + character description once. Every episode inherits it for free. A vague bible produces vague episodes.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Use a base seed</strong> for visual consistency across episodes in the same series. Settings -&gt; Series -&gt; base_seed. Keeps character faces + palettes stable.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Test voices before committing</strong> - Settings -&gt; Voice Profiles -&gt; Test. A voice that sounds fine on a single sentence can be grating over 10 minutes.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Review the script before scenes run</strong> - scene generation is 80% of wall time. Catching a bad script at the script-tab stage saves 20 minutes per episode.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Regenerate individual scenes</strong> instead of the whole episode when one frame looks wrong. The regenerate-scene flow reuses everything else.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Negative prompts are cheap insurance</strong> - add <code className="font-mono text-xs">blurry, extra fingers, text overlay, watermark</code> to the series negative_prompt.</li>
      </ul>

      <SubHeading id="tips-speed" title="Generating Faster" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Parallel episodes, not parallel scenes</strong> - running 3 episodes in parallel on a single GPU is slower than one episode at a time (GPU contention). Running 3 episodes across 3 ComfyUI servers is ~2.8x faster.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Use Edge TTS for drafts</strong> - it's free and runs in 2-5 seconds per minute of audio. Switch to Kokoro/ElevenLabs once the script is locked.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Keep LM Studio + ComfyUI warm</strong> - the first generation after boot is slow because models load into VRAM. Subsequent generations skip that.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Shorts_first priority</strong> - Activity Monitor -&gt; Priority. Queues long-form behind shorts so your daily uploads don't wait on a 2-hour long-form run.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Bulk-generate during off-hours</strong> - queue 10 episodes before bed. The worker processes them sequentially, using the GPU 100% through the night.</li>
      </ul>

      <SubHeading id="tips-workflow" title="Workflow" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">One series per channel</strong> - don't try to reuse a series across channels with different audiences. The tone drifts.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Topic lists in spreadsheets</strong> - paste 50 topics into bulk-generate. The LLM will write 50 scripts in ~20 minutes; you review and kill the duds.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Schedule, don't publish manually</strong> - Calendar -&gt; drag to a date/time. Consistent upload cadence matters more than upload count.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Back up after major milestones</strong> - finished a 10-episode season? Click Backup now. Cheap insurance.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Separate series for experiments</strong> - clone a working series into "<em>series-name</em> experiments" before testing a new voice / visual style. Keeps the prod series unpolluted.</li>
      </ul>

      <SubHeading id="tips-youtube" title="YouTube Growth" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">First 3 seconds decide everything</strong> - write the hook yourself. The LLM is good at filler, mediocre at openers. Edit the hook in the script tab before approving.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Thumbnails matter more than titles</strong> - the SEO endpoint writes a title, but you should manually upload a thumbnail for every video until you have a proven auto-generated style.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Disclose AI-generated content</strong> - YouTube requires it for synthetic media that could be mistaken for real. The checkbox is during the upload dialog on youtube.com. Do it on every upload.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Upload cadence beats variety</strong> - 1 video/day for 30 days beats 3 videos/day for 10 days, every time. Schedule accordingly.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Community tab posts</strong> - not in Drevalis yet. Check the roadmap; in the meantime post polls manually the day before a video drops.</li>
      </ul>

      <SubHeading id="tips-safety" title="Safety & Compliance" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Don't impersonate real people.</strong> Voice cloning of a public figure without consent invites takedowns and lawsuits. Use fictional characters or voice actors with clearance.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Stock music licenses.</strong> If you upload your own tracks to <code className="font-mono text-xs">storage/music/library/</code>, make sure you have commercial-use rights. YouTube's Content ID is aggressive.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Claim fair use carefully.</strong> Commentary on copyrighted material has a legal basis in the US but not universally. Know your audience's jurisdiction.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Age-gating and sensitive topics.</strong> If you produce content that discusses self-harm, eating disorders, or political topics, tag videos appropriately on YouTube. Algorithmic deprioritization of un-tagged sensitive content is worse than outright removal.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Acceptable Use Policy.</strong> Read <a href="https://drevalis.com/acceptable-use" className="text-accent underline" target="_blank" rel="noreferrer">drevalis.com/acceptable-use</a>. Violation can revoke your license without refund.</li>
      </ul>
    </section>
  );
}

export default ProTips;
