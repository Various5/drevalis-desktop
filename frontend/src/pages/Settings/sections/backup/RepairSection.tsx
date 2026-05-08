import { Wrench } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import type { RepairReport, StorageProbe } from './types';
import { formatBytes, formatRelativeAge } from './utils';

interface RepairSectionProps {
  repairing: boolean;
  probing: boolean;
  repairReport: RepairReport | null;
  probeReport: StorageProbe | null;
  onRepair: () => void;
  onProbe: (force?: boolean) => void;
}

export function RepairSection({
  repairing,
  probing,
  repairReport,
  probeReport,
  onRepair,
  onProbe,
}: RepairSectionProps) {
  return (
    <Card className="p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h4 className="font-semibold flex items-center gap-2">
            <Wrench className="w-4 h-4" />
            Repair media links
          </h4>
          <p className="text-sm text-txt-secondary mt-1">
            Relink <code>media_assets</code> rows to files on disk after a rough restore or
            manual copy. Non-destructive: only rows whose current path is broken get updated.
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => onProbe(false)} disabled={probing} variant="ghost">
            {probing ? 'Probing...' : 'Diagnose serving'}
          </Button>
          <Button onClick={onRepair} disabled={repairing} variant="primary">
            {repairing ? 'Scanning...' : 'Repair now'}
          </Button>
        </div>
      </div>
      {probeReport && (
        <div className="mt-4 space-y-3 rounded bg-bg-elevated p-3 text-xs">
          {probeReport.cached && (
            <div className="flex items-center justify-between rounded bg-bg-base/50 px-2 py-1 text-[11px] text-txt-secondary">
              <span>
                Cached
                {(() => {
                  const age = formatRelativeAge(probeReport.cached_at);
                  return age ? ` ${age}` : '';
                })()}
                {' · 5 min TTL'}
              </span>
              <button
                type="button"
                onClick={() => onProbe(true)}
                disabled={probing}
                className="text-accent hover:underline disabled:opacity-50"
              >
                {probing ? 'Refreshing...' : 'Refresh now'}
              </button>
            </div>
          )}
          <div className="font-mono text-txt-primary space-y-0.5">
            <div>
              inside container: {probeReport.storage_base_path}
              {probeReport.process_uid !== null && (
                <> · uid={probeReport.process_uid}</>
              )}
              {probeReport.mount_fs && (
                <>
                  {' '}· fs={probeReport.mount_fs}
                  {(probeReport.mount_fs === 'cifs' ||
                    probeReport.mount_fs === 'smb3' ||
                    probeReport.mount_fs === 'nfs' ||
                    probeReport.mount_fs === 'nfs4') && (
                    <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-accent/10 text-accent">
                      {probeReport.mount_fs === 'cifs' || probeReport.mount_fs === 'smb3'
                        ? 'SMB/CIFS share'
                        : 'NFS share'}
                    </span>
                  )}
                </>
              )}
            </div>
            {probeReport.host_source_path && (
              <div className="text-accent">on host: {probeReport.host_source_path}</div>
            )}
          </div>
          {probeReport.hints.length > 0 && (
            <ul className="space-y-2">
              {probeReport.hints.map((h, i) => (
                <li
                  key={i}
                  className="rounded bg-amber-500/10 border border-amber-500/30 p-2 text-amber-200"
                >
                  {h}
                </li>
              ))}
            </ul>
          )}
          {probeReport.top_level_entries && (
            <details className="rounded bg-bg-base p-2" open>
              <summary className="cursor-pointer text-txt-secondary">
                What the container sees at /app/storage
                {typeof probeReport.total_visible_count === 'number' && (
                  <span className="ml-2 text-txt-muted">
                    ({probeReport.total_visible_count} entries,{' '}
                    {formatBytes(probeReport.total_visible_bytes || 0)} visible)
                  </span>
                )}
              </summary>
              {probeReport.top_level_entries.length === 0 ? (
                <div className="mt-2 text-txt-muted">
                  No top-level entries. The storage directory is empty inside the container —
                  whatever you have on the host is not reaching this bind mount.
                </div>
              ) : (
                <div className="mt-2 space-y-1 font-mono text-[11px]">
                  {probeReport.top_level_entries.map((e, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <span
                        className={[
                          'shrink-0 w-10 text-[10px] uppercase font-sans tracking-wider',
                          e.kind === 'dir'
                            ? 'text-accent'
                            : e.kind === 'file'
                              ? 'text-txt-secondary'
                              : 'text-txt-muted',
                        ].join(' ')}
                      >
                        {e.kind || '?'}
                      </span>
                      <span className="min-w-0 truncate text-txt-primary">{e.name}</span>
                      <span className="ml-auto shrink-0 text-txt-muted">
                        {e.kind === 'file' && typeof e.size_bytes === 'number'
                          ? formatBytes(e.size_bytes)
                          : e.kind === 'dir'
                            ? `${e.child_count}${e.child_count_capped ? '+' : ''} children`
                            : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-2 text-[10px] text-txt-muted">
                If what you see here doesn't match what's in{' '}
                <code className="bg-bg-elevated px-1 rounded">
                  %USERPROFILE%\Drevalis\storage\
                </code>{' '}
                on your host, the running container was started from a different directory than
                the one you copied files into. In a terminal at{' '}
                <code className="bg-bg-elevated px-1 rounded">%USERPROFILE%\Drevalis\</code>:{' '}
                <code className="bg-bg-elevated px-1 rounded">
                  docker compose down; docker compose up -d
                </code>
                .
              </div>
            </details>
          )}
          {probeReport.samples.length > 0 && (
            <details className="rounded bg-bg-base p-2">
              <summary className="cursor-pointer text-txt-secondary">
                Probe samples ({probeReport.samples.length})
              </summary>
              <div className="mt-2 space-y-1 font-mono">
                {probeReport.samples.map((s, i) => (
                  <div key={i} className="truncate flex items-start gap-2">
                    <span className="shrink-0 w-16 font-sans text-[10px] uppercase tracking-wider text-txt-tertiary">
                      {s.asset_type}
                    </span>
                    <span
                      className={[
                        'shrink-0 w-16 font-sans text-[10px] uppercase tracking-wider',
                        s.readable
                          ? 'text-emerald-300'
                          : s.exists
                            ? 'text-amber-300'
                            : 'text-error',
                      ].join(' ')}
                    >
                      {s.readable ? 'readable' : s.exists ? 'exists' : 'missing'}
                    </span>
                    <span className="min-w-0 truncate text-txt-secondary">
                      {s.abs_path}
                      {s.error && <> — {s.error}</>}
                    </span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
      {repairReport && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="rounded bg-bg-elevated p-3">
              <div className="text-txt-muted uppercase tracking-wider mb-1">Scanned</div>
              <div className="text-txt-primary text-lg font-semibold">{repairReport.scanned}</div>
            </div>
            <div className="rounded bg-bg-elevated p-3">
              <div className="text-txt-muted uppercase tracking-wider mb-1">Already OK</div>
              <div className="text-txt-primary text-lg font-semibold">
                {repairReport.already_ok}
              </div>
            </div>
            <div className="rounded bg-emerald-500/10 p-3">
              <div className="text-emerald-300 uppercase tracking-wider mb-1">Relinked</div>
              <div className="text-emerald-200 text-lg font-semibold">{repairReport.relinked}</div>
            </div>
            <div
              className={`rounded p-3 ${
                repairReport.unresolved > 0 ? 'bg-amber-500/10' : 'bg-bg-elevated'
              }`}
            >
              <div
                className={`uppercase tracking-wider mb-1 ${
                  repairReport.unresolved > 0 ? 'text-amber-300' : 'text-txt-muted'
                }`}
              >
                Unresolved
              </div>
              <div
                className={`text-lg font-semibold ${
                  repairReport.unresolved > 0 ? 'text-amber-200' : 'text-txt-primary'
                }`}
              >
                {repairReport.unresolved}
              </div>
            </div>
          </div>
          {repairReport.relinked_paths.length > 0 && (
            <details className="rounded bg-bg-elevated p-3 text-xs">
              <summary className="cursor-pointer text-txt-secondary">
                Relinked paths ({repairReport.relinked_paths.length}
                {repairReport.relinked > repairReport.relinked_paths.length ? '+' : ''})
              </summary>
              <div className="mt-2 space-y-1 font-mono">
                {repairReport.relinked_paths.map((p, i) => (
                  <div key={i} className="truncate">
                    <span className="text-txt-muted">{p.from || '(empty)'}</span>
                    <span className="text-emerald-300 mx-1">→</span>
                    <span className="text-txt-primary">{p.to}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
          {repairReport.unresolved_paths.length > 0 && (
            <details className="rounded bg-amber-500/5 p-3 text-xs">
              <summary className="cursor-pointer text-amber-300">
                Unresolved paths ({repairReport.unresolved_paths.length}
                {repairReport.unresolved > repairReport.unresolved_paths.length ? '+' : ''})
              </summary>
              <div className="mt-2 space-y-1 font-mono text-txt-secondary">
                {repairReport.unresolved_paths.map((p, i) => (
                  <div key={i} className="truncate flex items-start gap-2">
                    <span className="shrink-0 font-sans text-[10px] uppercase tracking-wider">
                      {p.basename_on_disk ? (
                        <span className="text-amber-300">bytes nearby</span>
                      ) : (
                        <span className="text-error">missing</span>
                      )}
                    </span>
                    <span className="min-w-0 truncate">{p.path}</span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-txt-muted">
                <strong className="text-txt-primary">bytes nearby</strong> — the filename exists
                somewhere under the storage root but the repair couldn't confidently match it
                (ambiguous duplicates, missing size on DB row). You can often recover by
                regenerating the specific scene; safe to ignore otherwise.
                <br />
                <strong className="text-txt-primary">missing</strong> — the file truly isn't on
                disk. Regenerate the affected episode or delete the orphan row.
              </p>
            </details>
          )}
          {repairReport.storage_base_abs && (
            <p className="text-[11px] text-txt-tertiary mt-2 font-mono">
              storage root: {repairReport.storage_base_abs}
              {typeof repairReport.indexed_files === 'number' && (
                <> · indexed {repairReport.indexed_files} files</>
              )}
            </p>
          )}
          {(repairReport.sample_db_paths?.length || repairReport.sample_disk_paths?.length) ? (
            <div className="mt-3 grid md:grid-cols-2 gap-3">
              <div className="rounded bg-bg-elevated p-3">
                <div className="text-[10px] text-txt-tertiary uppercase tracking-wider mb-2">
                  Sample DB paths ({repairReport.sample_db_paths?.length ?? 0})
                </div>
                <div className="font-mono text-[11px] text-txt-primary space-y-1 break-all">
                  {(repairReport.sample_db_paths || []).length === 0 ? (
                    <div className="text-txt-muted">No media_assets rows with a file_path.</div>
                  ) : (
                    (repairReport.sample_db_paths || []).map((p, i) => (
                      <div key={i}>{p}</div>
                    ))
                  )}
                </div>
              </div>
              <div className="rounded bg-bg-elevated p-3">
                <div className="text-[10px] text-txt-tertiary uppercase tracking-wider mb-2">
                  Sample disk paths ({repairReport.sample_disk_paths?.length ?? 0})
                </div>
                <div className="font-mono text-[11px] text-txt-primary space-y-1 break-all">
                  {(repairReport.sample_disk_paths || []).length === 0 ? (
                    <div className="text-txt-muted">
                      Index empty — container sees no files under storage_root. The bind mount
                      is pointing at the wrong directory.
                    </div>
                  ) : (
                    (repairReport.sample_disk_paths || []).map((p, i) => (
                      <div key={i}>{p}</div>
                    ))
                  )}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}
