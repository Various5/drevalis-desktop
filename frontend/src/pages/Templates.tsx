import { TemplatesSection } from '@/pages/Settings/sections/TemplatesSection';

// Templates — reusable series presets. Promoted to a top-level Create page in
// Phase 1 (was Settings → Content → Templates). The section component is
// shared; this route just hosts it with its own banner. See
// docs/goals/phases/phase-1.md.
function Templates() {
  return (
    <div>
      <p className="text-sm text-txt-secondary mb-6">
        Reusable series presets. Capture a series' tone, visual style, voice,
        captions, and music settings once, then apply them when creating new
        series.
      </p>
      <TemplatesSection />
    </div>
  );
}

export default Templates;
