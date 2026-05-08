import { Server, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, InfoBox, Warning } from './_shared';

export function WorkerManagement() {
  return (
    <section id="worker-management" className="mb-16 scroll-mt-4">
      <SectionHeading id="worker-management-heading" icon={Server} title="Worker Management" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-5">
        All heavy processing (script generation, TTS, scene generation, assembly) runs as background jobs
        in the arq worker process. The Activity Monitor and Jobs page give you visibility and control over
        the worker queue.
      </p>

      <SubHeading id="worker-health" title="Worker Health & Monitoring" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The <strong className="text-txt-primary">Activity Monitor</strong> (floating panel, bottom-right)
        shows all active and recently completed jobs with real-time step-by-step progress via WebSocket.
        For a deeper view, go to <strong className="text-txt-primary">Jobs</strong> in the sidebar:
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4 mb-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Active Jobs</strong> — currently running pipeline jobs, their step, progress percentage, and elapsed time.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Queue Status</strong> — jobs waiting to start. Shows queue depth and estimated wait time.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Recent History</strong> — completed and failed jobs with per-step duration metrics.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Cleanup Stuck Jobs</strong> — forcibly marks all hung jobs as failed so they can be retried.</li>
      </ul>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Settings → Health shows the current status of all connected services: database, Redis, ComfyUI
        servers, and FFmpeg. A green check on all services means the worker can operate normally.
      </p>

      <SubHeading id="worker-priority" title="Priority Queue" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The arq worker uses a two-tier priority queue:
      </p>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="surface p-4 rounded-lg border-l-2 border-accent">
          <p className="text-sm font-semibold text-txt-primary mb-1">High Priority</p>
          <ul className="space-y-1 text-xs text-txt-secondary">
            <li className="flex gap-1.5"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />YouTube Shorts generation</li>
            <li className="flex gap-1.5"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />Retry jobs (failed steps)</li>
            <li className="flex gap-1.5"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />Single scene regeneration</li>
            <li className="flex gap-1.5"><ChevronRight size={11} className="text-accent shrink-0 mt-0.5" />Reassemble (captions + assembly only)</li>
          </ul>
        </div>
        <div className="surface p-4 rounded-lg border-l-2 border-border">
          <p className="text-sm font-semibold text-txt-primary mb-1">Standard Priority</p>
          <ul className="space-y-1 text-xs text-txt-secondary">
            <li className="flex gap-1.5"><ChevronRight size={11} className="text-txt-tertiary shrink-0 mt-0.5" />Long-form video generation</li>
            <li className="flex gap-1.5"><ChevronRight size={11} className="text-txt-tertiary shrink-0 mt-0.5" />Audiobook generation</li>
            <li className="flex gap-1.5"><ChevronRight size={11} className="text-txt-tertiary shrink-0 mt-0.5" />Voice preview generation</li>
          </ul>
        </div>
      </div>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        When both a Short and a long-form video are queued, the Short will always start first.
        This prevents a 60-minute documentary job from blocking a 5-minute Shorts job.
      </p>
      <InfoBox>
        The worker runs up to 4 jobs simultaneously (<code className="font-mono text-xs text-accent">MAX_CONCURRENT_GENERATIONS=4</code>). Lower this if your GPU runs out of VRAM when multiple ComfyUI jobs run in parallel.
      </InfoBox>

      <SubHeading id="worker-restart" title="Restarting the Worker" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        If the worker process becomes unresponsive or you need to apply configuration changes:
      </p>
      <div className="space-y-2">
        {[
          { label: 'Docker (recommended)', cmd: 'docker compose restart worker' },
          { label: 'Local dev', cmd: 'Ctrl+C to stop, then re-run: python -m arq src.drevalis.workers.settings.WorkerSettings' },
        ].map(item => (
          <div key={item.label} className="surface p-3 rounded-lg">
            <p className="text-xs font-semibold text-txt-primary mb-1">{item.label}</p>
            <code className="text-xs font-mono text-accent">{item.cmd}</code>
          </div>
        ))}
      </div>
      <Warning>
        Restarting the worker will kill any currently running jobs. Those jobs will remain in "generating" state until you run Cleanup Stuck Jobs, after which they can be retried. Completed pipeline steps are preserved — the retry resumes from the failed step.
      </Warning>
    </section>
  );
}

export default WorkerManagement;
