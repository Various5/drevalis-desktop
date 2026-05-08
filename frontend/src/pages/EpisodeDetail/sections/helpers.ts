// ---------------------------------------------------------------------------
// Shared helpers, types, and constants for EpisodeDetail section components
// ---------------------------------------------------------------------------

/** Scene data built from script JSONB + media_assets, used by Script and Scenes tabs. */
export interface SceneDataExtended {
  sceneNumber: number;
  imageUrl: string | null;
  prompt: string;
  durationSeconds: number;
  narration: string;
  visualPrompt: string;
  keywords: string[];
}

/** Per-scene in-progress edits tracked by ScriptTab. */
export interface EditedScene {
  narration?: string;
  visual_prompt?: string;
  duration_seconds?: number;
  keywords?: string[];
}

/** Music track returned by the music-list endpoint. */
export interface MusicTrack {
  filename: string;
  path: string;
  mood: string;
  duration: number;
}

/** Format seconds into an SRT/ASS-style HH:MM:SS,mmm timestamp. */
export function formatTimestamp(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const millis = Math.round((totalSeconds % 1) * 1000);
  return (
    String(hours).padStart(2, '0') +
    ':' +
    String(minutes).padStart(2, '0') +
    ':' +
    String(seconds).padStart(2, '0') +
    ',' +
    String(millis).padStart(3, '0')
  );
}

/** Shared music mood presets — used by CaptionsTab (inline panel) and MusicTab. */
export const MUSIC_MOODS = [
  { value: 'epic', label: 'Epic', desc: 'Cinematic orchestral' },
  { value: 'calm', label: 'Calm', desc: 'Soft ambient piano' },
  { value: 'dark', label: 'Dark', desc: 'Suspenseful atmosphere' },
  { value: 'happy', label: 'Happy', desc: 'Bright cheerful' },
  { value: 'sad', label: 'Sad', desc: 'Melancholic emotional' },
  { value: 'mysterious', label: 'Mysterious', desc: 'Ethereal suspense' },
  { value: 'action', label: 'Action', desc: 'High-energy driving' },
  { value: 'romantic', label: 'Romantic', desc: 'Warm intimate' },
  { value: 'horror', label: 'Horror', desc: 'Dark creepy' },
  { value: 'comedy', label: 'Comedy', desc: 'Playful bouncy' },
  { value: 'inspiring', label: 'Inspiring', desc: 'Uplifting triumphant' },
  { value: 'chill', label: 'Chill', desc: 'Lo-fi relaxed' },
] as const;

/** Caption style preset definitions — used by CaptionsTab. */
export const CAPTION_PRESETS: Array<{ value: string | null; label: string; desc: string }> = [
  { value: '', label: 'Series Default', desc: 'Use the series setting' },
  { value: 'youtube_highlight', label: 'Highlight', desc: 'Words light up as spoken' },
  { value: 'karaoke', label: 'Karaoke', desc: 'One word at a time' },
  { value: 'tiktok_pop', label: 'TikTok Pop', desc: 'Words pop in with scale' },
  { value: 'buzzword', label: 'Buzzword', desc: 'Keywords pop up center' },
  { value: 'minimal', label: 'Minimal', desc: 'Small subtle text' },
  { value: 'classic', label: 'Classic', desc: 'White on black outline' },
  { value: null, label: 'No Captions', desc: 'Remove all captions' },
];
