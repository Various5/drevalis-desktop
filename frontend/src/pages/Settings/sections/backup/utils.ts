// Shared utility functions for BackupSection sub-components.

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatRelativeAge(iso?: string): string | null {
  if (!iso) return null;
  const cachedAt = Date.parse(iso);
  if (Number.isNaN(cachedAt)) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - cachedAt) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

export function hostHintFromVmLabel(path: string | null | undefined): string | null {
  // Docker Desktop on Windows/macOS labels bind-mounted host directories
  // with VM-internal prefixes. Map them back to the real user-visible
  // Windows/macOS equivalent so the operator can paste it into Explorer.
  if (!path) return null;
  const vmPrefixes = ['/project/', '/run/desktop/mnt/', '/mnt/host_mnt/', '/host_mnt/'];
  for (const prefix of vmPrefixes) {
    if (path.startsWith(prefix)) {
      const tail = path.slice(prefix.length);
      // Heuristic: the compose directory's basename is the same in both
      // worlds, so tail under the prefix maps 1:1 to ``%USERPROFILE%\<tail>``
      // on Windows (or ``~/<tail>`` on macOS) for the default install.
      const winPath = '%USERPROFILE%\\' + tail.replace(/\//g, '\\');
      const macPath = '~/' + tail;
      return `Windows: ${winPath}   ·   macOS: ${macPath}`;
    }
  }
  if (path.startsWith('/var/lib/docker/volumes/')) {
    return (
      'This is a Docker NAMED VOLUME, not a bind mount — the backup lives ' +
      "inside Docker Desktop's VM and isn't visible in Windows Explorer. " +
      'Set BACKUP_DIRECTORY in .env to a bind-mounted path, or use ' +
      '"docker cp drevalis-app-1:<path> ." to pull files to your host.'
    );
  }
  return null;
}
