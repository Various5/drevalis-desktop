import { EpisodesSection } from './EpisodesSection';
import type { EpisodesSectionProps } from './EpisodesSection';

// ---------------------------------------------------------------------------
// EpisodesTab
//
// The "Episodes" tab on the SeriesDetail page. Primary task: manage episodes.
// This component is intentionally thin — it just wraps EpisodesSection so the
// parent monolith can render it under a tab without pulling in UI layout
// decisions from the section itself.
// ---------------------------------------------------------------------------

export interface EpisodesTabProps extends EpisodesSectionProps {}

export function EpisodesTab(props: EpisodesTabProps) {
  return <EpisodesSection {...props} />;
}
