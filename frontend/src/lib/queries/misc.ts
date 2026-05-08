import { useQuery } from '@tanstack/react-query';
import { health, license, settings, audiobooks, voiceProfiles } from '@/lib/api';
import { keys } from './keys';

// ---------------------------------------------------------------------------
// Lightweight read-only queries (Phase 3.2)
// ---------------------------------------------------------------------------
//
// Settings sub-screens, the License section, and the audiobook /
// voice-profile lists used to manage their own ``useState(true)`` +
// ``useEffect`` fetch dance. These hooks collapse them to one line.

export function useHealth() {
  return useQuery({
    queryKey: keys.health.overall(),
    queryFn: () => health.check(),
  });
}

// Detailed system-health: per-service status (ComfyUI, LLM, voices,
// FFmpeg, ...). Polls every 60s — much slower than the basic ``/health``
// liveness probe because the per-service check can hammer external
// servers. Used by the Dashboard's ``SystemHealthCard`` to surface
// degraded services without forcing the user into Settings.
export function useSystemHealth() {
  return useQuery({
    queryKey: ['settings', 'health'] as const,
    queryFn: () => settings.health(),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

export function useStorage() {
  return useQuery({
    queryKey: keys.storage.overall(),
    queryFn: () => settings.storage(),
  });
}

export function useLicenseStatus() {
  return useQuery({
    queryKey: keys.license.status(),
    queryFn: () => license.status(),
  });
}

export function useAudiobooks() {
  return useQuery({
    queryKey: keys.audiobooks.list(),
    queryFn: () => audiobooks.list(),
  });
}

export function useAudiobook(id: string | undefined) {
  return useQuery({
    queryKey: keys.audiobooks.detail(id ?? ''),
    queryFn: () => audiobooks.get(id ?? ''),
    enabled: Boolean(id),
  });
}

export function useVoiceProfiles(params?: {
  provider?: string;
  language_code?: string;
}) {
  return useQuery({
    queryKey: keys.voiceProfiles.list(params),
    queryFn: () => voiceProfiles.list(params),
  });
}
