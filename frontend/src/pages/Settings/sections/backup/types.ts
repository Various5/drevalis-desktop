// Shared types for BackupSection sub-components.
// These are co-located here so every child imports from one place
// and the parent re-uses the same definitions.

export interface BackupArchive {
  filename: string;
  size_bytes: number;
  created_at: string;
}

export interface BackupListResponse {
  backup_directory: string;
  backup_directory_abs?: string;
  backup_directory_host_source?: string | null;
  retention: number;
  auto_enabled: boolean;
  archives: BackupArchive[];
}

export interface RepairReport {
  scanned: number;
  already_ok: number;
  relinked: number;
  unresolved: number;
  relinked_paths: Array<{ from: string; to: string }>;
  unresolved_paths: Array<{ path: string; basename_on_disk: boolean }>;
  storage_base_abs?: string;
  indexed_files?: number;
  sample_db_paths?: string[];
  sample_disk_paths?: string[];
}

export interface StorageProbe {
  storage_base_path: string;
  storage_base_exists: boolean;
  storage_base_is_symlink: boolean;
  episodes_dir_exists: boolean;
  episodes_dir_is_symlink: boolean;
  audiobooks_dir_exists: boolean;
  api_auth_token_configured: boolean;
  api_auth_blocks_storage: boolean;
  process_uid: number | null;
  process_gid: number | null;
  mount_fs: string | null;
  host_source_path: string | null;
  top_level_entries?: Array<{
    name?: string;
    kind?: 'file' | 'dir' | 'other';
    size_bytes?: number;
    child_count?: number;
    child_count_capped?: boolean;
    error?: string;
  }>;
  total_visible_bytes?: number;
  total_visible_count?: number;
  samples: Array<{
    asset_type: string;
    file_path: string;
    episode_id: string | null;
    abs_path: string | null;
    exists: boolean;
    readable: boolean;
    is_symlink: boolean;
    size_bytes: number | null;
    url_served_at: string | null;
    error: string | null;
  }>;
  hints: string[];
  cached?: boolean;
  cached_at?: string;
}

export interface RestoreProgress {
  stage: string;
  progress_pct: number;
  message: string;
}
