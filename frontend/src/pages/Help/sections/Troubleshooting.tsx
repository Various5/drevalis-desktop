import { AlertTriangle } from 'lucide-react';
import { SectionHeading, SubHeading, Tip, InfoBox, CodeBlock } from './_shared';

export function Troubleshooting() {
  return (
    <section id="troubleshooting" className="mb-16 scroll-mt-4">
      <SectionHeading id="troubleshooting-heading" icon={AlertTriangle} title="Troubleshooting" />

      <SubHeading id="stuck-generation" title="Generation Stuck or Hung" />
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-sm font-semibold text-txt-primary mb-2">Symptom</p>
        <p className="text-sm text-txt-secondary mb-3">The Activity Monitor shows a job has been running for a very long time with no progress updates, or the progress bar is frozen.</p>
        <p className="text-sm font-semibold text-txt-primary mb-2">Solution</p>
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-txt-secondary ml-2">
          <li>Check the Activity Monitor for the stuck job — click the X button to cancel it.</li>
          <li>If the cancel button is unresponsive, go to Jobs (in Settings) → click <strong className="text-txt-primary">Cleanup Stuck Jobs</strong>. This forcibly marks all hung jobs as failed.</li>
          <li>After cleanup, use <strong className="text-txt-primary">Retry</strong> on the episode — it will skip completed steps and resume from where it failed.</li>
          <li>If ComfyUI is the source of the hang, restart your ComfyUI instance and retry.</li>
        </ol>
      </div>
      <Tip>
        The arq worker has a 2-hour job timeout. If a job doesn't complete within 2 hours, it is automatically marked as failed and can be retried.
      </Tip>

      <SubHeading id="video-playback" title="Video Won't Play in Browser" />
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-sm font-semibold text-txt-primary mb-2">Symptom</p>
        <p className="text-sm text-txt-secondary mb-3">The generated MP4 plays in the app's video player but shows a blank frame or codec error in some external players or browsers.</p>
        <p className="text-sm font-semibold text-txt-primary mb-2">Cause</p>
        <p className="text-sm text-txt-secondary mb-3">Some ComfyUI video generation workflows output video with pixel formats (yuv444p, yuv420p10le, etc.) that are not universally supported. Drevalis Creator Studio normalizes all video to yuv420p (H.264 High profile) during the Assembly step, but this step may be skipped if the episode is in an intermediate state.</p>
        <p className="text-sm font-semibold text-txt-primary mb-2">Solution</p>
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-txt-secondary ml-2">
          <li>Click <strong className="text-txt-primary">Reassemble</strong> on the episode. This re-runs the Assembly step, which forces yuv420p encoding.</li>
          <li>If the issue persists, check the episode's generation job logs for FFmpeg error output.</li>
          <li>Verify FFmpeg is compiled with libx264 support: run <code className="font-mono text-xs text-accent">ffmpeg -codecs | grep h264</code></li>
        </ol>
      </div>

      <SubHeading id="comfyui-connection" title="No ComfyUI Connection" />
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-sm font-semibold text-txt-primary mb-2">Symptom</p>
        <p className="text-sm text-txt-secondary mb-3">Settings → ComfyUI shows "Connection failed" or scene generation fails with a "ComfyUI unreachable" error.</p>
        <p className="text-sm font-semibold text-txt-primary mb-2">Checklist</p>
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-txt-secondary ml-2">
          <li>Verify ComfyUI is running — open the ComfyUI URL directly in your browser.</li>
          <li>Check the URL format — it should include the protocol: <code className="font-mono text-xs text-accent">http://localhost:8188</code> (not just <code className="font-mono text-xs text-accent">localhost:8188</code>).</li>
          <li>If running ComfyUI in Docker, ensure the port is exposed and the URL uses the correct host (e.g. <code className="font-mono text-xs text-accent">http://host.docker.internal:8188</code> when the backend is also in Docker).</li>
          <li>If ComfyUI requires an API key, ensure it's entered in the server settings.</li>
          <li>Check firewall rules — the backend must be able to reach the ComfyUI port.</li>
        </ol>
      </div>

      <SubHeading id="captions-missing" title="Captions Not Showing in Video" />
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-sm font-semibold text-txt-primary mb-2">Symptom</p>
        <p className="text-sm text-txt-secondary mb-3">The generated video plays without any caption overlay, even though a caption style is configured.</p>
        <p className="text-sm font-semibold text-txt-primary mb-2">Common Causes & Fixes</p>
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-txt-secondary ml-2">
          <li><strong className="text-txt-primary">Caption style changed after generation.</strong> After changing the caption style in episode settings, you must click <strong>Reassemble</strong>. The new style is not applied retroactively.</li>
          <li><strong className="text-txt-primary">Captions step failed silently.</strong> Check the generation job for the Captions step. If failed, retry that step specifically.</li>
          <li><strong className="text-txt-primary">faster-whisper not installed.</strong> The captions step requires faster-whisper. Verify it's installed in the backend environment.</li>
          <li><strong className="text-txt-primary">ASS subtitle file missing.</strong> If the <code className="font-mono text-xs">captions/</code> directory for the episode is empty, the captions file was never generated. Re-run the Captions step.</li>
        </ol>
      </div>

      <SubHeading id="music-missing" title="Music Not Generated" />
      <div className="surface p-4 rounded-lg mb-4">
        <p className="text-sm font-semibold text-txt-primary mb-2">Symptom</p>
        <p className="text-sm text-txt-secondary mb-3">The final video has no background music, or the music generation request fails silently.</p>
        <p className="text-sm font-semibold text-txt-primary mb-2">Checklist</p>
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-txt-secondary ml-2">
          <li><strong className="text-txt-primary">Mood not set.</strong> A mood must be selected on the series or episode before music can be generated. Go to the series settings and set a music mood.</li>
          <li><strong className="text-txt-primary">AceStep not installed.</strong> Open ComfyUI in your browser and check if the AceStep custom node is available. If not, install it via ComfyUI Manager.</li>
          <li><strong className="text-txt-primary">AceStep model weights missing.</strong> AceStep requires model weights separate from the custom node. Check the AceStep documentation for required model files.</li>
          <li><strong className="text-txt-primary">Wrong workflow.</strong> Ensure the AceStep workflow is registered in Settings → ComfyUI Workflows and is selected in the music settings.</li>
          <li><strong className="text-txt-primary">Curated library fallback.</strong> If AceStep is unavailable, Drevalis Creator Studio falls back to the curated music library. Ensure the library has tracks for your chosen mood in <code className="font-mono text-xs text-accent">storage/music/library/{'{mood}'}/</code>.</li>
        </ol>
      </div>

      <SubHeading id="ts-uploads" title="YouTube Upload Fails" />
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li><strong className="text-txt-primary">401 / token expired</strong> - click Reconnect in Settings -&gt; YouTube. Happens every ~6 months as Google rotates refresh tokens.</li>
        <li><strong className="text-txt-primary">quotaExceeded</strong> - YouTube Data API has a daily quota (10 000 units default). One upload costs 1600. Wait 24 hours or request a quota increase in Google Cloud Console.</li>
        <li><strong className="text-txt-primary">no_channel_selected / 400</strong> - assign a channel to the series (Series detail -&gt; YouTube Channel) or, for scheduled posts, to the post itself.</li>
        <li><strong className="text-txt-primary">Retry mid-upload</strong> - uploads retry 3 times automatically with fresh tokens each time. If all 3 fail, the Jobs tab shows the last error.</li>
      </ol>

      <SubHeading id="ts-license" title="License Gate / 402 Errors" />
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li><strong className="text-txt-primary">On every request right after install</strong> - wait 5 seconds; the license-state bootstrap runs in lifespan and the first request might race it. Fixed as of v0.2.0.</li>
        <li><strong className="text-txt-primary">After a renewal</strong> - the 24h heartbeat may not have fired yet. Settings -&gt; License -&gt; click <strong className="text-txt-primary">Refresh</strong> to force a heartbeat.</li>
        <li><strong className="text-txt-primary">License server 5xx</strong> - transient server outages are tolerated; your install keeps working with the stored JWT for 7 days offline.</li>
        <li><strong className="text-txt-primary">Still locked after renewal</strong> - email <a href="mailto:support@drevalis.com" className="text-accent underline">support@drevalis.com</a> with your license key (last 8 characters is enough).</li>
      </ol>

      <SubHeading id="ts-worker" title="Worker Stuck / Unhealthy" />
      <ol className="space-y-2 text-sm text-txt-secondary ml-4 mb-4 list-decimal list-inside">
        <li>Activity Monitor -&gt; Worker health should show a green dot.</li>
        <li>If red: click <strong className="text-txt-primary">Restart worker</strong>. Orphaned "generating" episodes are reset to "failed" so you can re-queue them.</li>
        <li>If the button doesn't help: <code className="font-mono text-xs">docker compose restart worker</code>.</li>
        <li>Worker OOM on long-form - check <code className="font-mono text-xs">docker compose logs worker</code> for the killed signal. Reduce <code className="font-mono text-xs">MAX_CONCURRENT_GENERATIONS</code> or add RAM.</li>
      </ol>

      <SubHeading id="ts-logs" title="Reading Logs" />
      <p className="text-sm text-txt-secondary mb-3">
        Logs are structured JSON. Useful fields: <code className="font-mono text-xs">event</code> (what), <code className="font-mono text-xs">episode_id</code>, <code className="font-mono text-xs">error</code>, <code className="font-mono text-xs">level</code>.
      </p>
      <CodeBlock>{`# Tail live logs\ndocker compose logs -f app worker\n\n# Last 100 errors from the worker\ndocker compose logs worker 2>&1 | grep '"level": "error"' | tail -100\n\n# Follow one specific episode across both services\ndocker compose logs -f app worker 2>&1 | grep "<episode-uuid>"`}</CodeBlock>
      <InfoBox>
        Tip: the in-app Logs page streams the same JSON into a searchable table. Use it instead of command-line grep when you can - filters by level, episode, and time range make pattern-spotting much faster.
      </InfoBox>

      <InfoBox>
        Check the backend logs for detailed error messages. When running via Docker, use <code className="font-mono text-xs">docker compose logs -f app</code> and <code className="font-mono text-xs">docker compose logs -f worker</code> to follow real-time output from the API and the arq job worker respectively.
      </InfoBox>

    </section>
  );
}

export default Troubleshooting;
