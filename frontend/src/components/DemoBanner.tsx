import { Sparkles, ArrowRight } from 'lucide-react';
import { useAuthMode } from '@/lib/useAuth';

/**
 * Sticky top banner rendered when the backend reports ``demo_mode=true``.
 *
 * Intentionally cheap to render (no state, one CSS gradient) so it can
 * live at the top of every authenticated page without cost. The CTA
 * links to pricing on the marketing site.
 */
export function DemoBanner() {
  const { demoMode, ready } = useAuthMode();
  if (!ready || !demoMode) return null;

  return (
    <div className="fixed top-0 left-0 right-0 h-8 z-[60] flex items-center justify-center gap-3 text-xs font-medium bg-gradient-to-r from-accent/30 via-accent/40 to-accent/30 text-txt-primary border-b border-accent/40 backdrop-blur-sm">
      <Sparkles size={14} className="text-accent" />
      <span>
        <strong>Live demo</strong> — feel free to click around. Data resets nightly. Generations are
        simulated, no GPU needed.
      </span>
      <a
        href="https://drevalis.com/pricing"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-accent hover:text-accent-hover transition-colors"
      >
        Buy the real thing
        <ArrowRight size={12} />
      </a>
    </div>
  );
}
