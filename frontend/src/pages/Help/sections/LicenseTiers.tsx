import { Star, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Tip } from './_shared';

export function LicenseTiers() {
  return (
    <section id="license-tiers" className="mb-16 scroll-mt-4">
      <SectionHeading id="license-tiers-heading" icon={Star} title="License & Tiers" />

      <p className="text-sm text-txt-secondary leading-relaxed mb-4">
        Every tier includes the full feature set. Tier caps only concurrency, channel count, and cloud-GPU access. Annual billing saves ~2 months.
      </p>

      <SubHeading id="tier-solo" title="Solo - $19/mo (or $190/yr)" />
      <ul className="space-y-1.5 text-sm text-txt-secondary ml-4 mb-5">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> 1 activated machine</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> 5 episodes per day</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> 1 connected YouTube channel</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Edge, Piper, Kokoro TTS (local + free cloud)</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Automatic updates</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Email support, best-effort</li>
      </ul>
      <Tip>Best for a single creator on one channel with a local GPU. If you need to test multi-channel or RunPod offload, upgrade to Pro.</Tip>

      <SubHeading id="tier-pro" title="Pro - $39/mo (or $390/yr)" />
      <ul className="space-y-1.5 text-sm text-txt-secondary ml-4 mb-5">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> 3 machines</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Unlimited episodes per day</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> 3 connected YouTube channels</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Audiobook Studio</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> ElevenLabs TTS support</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> RunPod cloud-GPU offload</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Long-form video generation</li>
      </ul>

      <SubHeading id="tier-studio" title="Studio - $99/mo (or $990/yr)" />
      <ul className="space-y-1.5 text-sm text-txt-secondary ml-4 mb-5">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> 5 machines</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Unlimited everything</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Unlimited YouTube channels</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> TikTok + Instagram publishing</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Public API access</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /> Priority email support</li>
      </ul>

      <SubHeading id="tier-compare" title="Feature Matrix" />
      <div className="overflow-x-auto mb-5">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border text-txt-secondary text-xs uppercase tracking-wider">
              <th className="text-left py-2 pr-4">Capability</th>
              <th className="text-center py-2 px-3">Solo</th>
              <th className="text-center py-2 px-3">Pro</th>
              <th className="text-center py-2 px-3">Studio</th>
            </tr>
          </thead>
          <tbody className="text-txt-secondary">
            <tr className="border-b border-border/50"><td className="py-2 pr-4">Machines</td><td className="text-center">1</td><td className="text-center">3</td><td className="text-center">5</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">Episodes per day</td><td className="text-center">5</td><td className="text-center">Unlimited</td><td className="text-center">Unlimited</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">YouTube channels</td><td className="text-center">1</td><td className="text-center">3</td><td className="text-center">Unlimited</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">Audiobook Studio</td><td className="text-center">-</td><td className="text-center">Yes</td><td className="text-center">Yes</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">ElevenLabs TTS</td><td className="text-center">-</td><td className="text-center">Yes</td><td className="text-center">Yes</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">RunPod offload</td><td className="text-center">-</td><td className="text-center">Yes</td><td className="text-center">Yes</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">Long-form video</td><td className="text-center">-</td><td className="text-center">Yes</td><td className="text-center">Yes</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">TikTok + Instagram</td><td className="text-center">-</td><td className="text-center">-</td><td className="text-center">Yes</td></tr>
            <tr className="border-b border-border/50"><td className="py-2 pr-4">Public API</td><td className="text-center">-</td><td className="text-center">-</td><td className="text-center">Yes</td></tr>
          </tbody>
        </table>
      </div>

      <SubHeading id="tier-grace" title="Grace Period & Renewal" />
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">24h online check</strong> - every 24 hours your install heartbeats the license server for a fresh JWT.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">7-day offline grace</strong> - if the heartbeat fails (network out, server down), your install keeps working for a full week without any connection.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Past the grace window</strong> - generation and upload lock until you renew. Existing files on disk stay - nothing is deleted.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Renewal</strong> - visit Settings -&gt; License -&gt; Manage Subscription (opens Stripe's billing portal).</li>
      </ul>
    </section>
  );
}

export default LicenseTiers;
