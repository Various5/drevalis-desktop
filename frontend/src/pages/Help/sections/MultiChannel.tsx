import { Youtube } from 'lucide-react';
import { SectionHeading, SubHeading, Tip, InfoBox, Warning } from './_shared';

export function MultiChannel() {
  return (
    <section id="multi-channel" className="mb-16 scroll-mt-4">
      <SectionHeading id="multi-channel-heading" icon={Youtube} title="Multi-Channel YouTube" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-5">
        Drevalis Creator Studio supports connecting multiple YouTube channels simultaneously — useful for
        managing separate channels per niche, language, or brand. Each series can be assigned to a
        specific channel for upload.
      </p>

      <SubHeading id="multi-channel-connect" title="Connecting Multiple Channels" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Each YouTube channel goes through its own OAuth flow. To connect a second (or third) channel:
      </p>
      <ol className="list-decimal list-inside space-y-2 text-sm text-txt-secondary ml-3 mb-4">
        <li>Go to Settings → YouTube.</li>
        <li>Click <strong className="text-txt-primary">Connect Another Channel</strong>. You will be redirected to Google's OAuth consent screen.</li>
        <li>Sign in with the Google account that owns the target channel and grant permissions.</li>
        <li>The channel appears in the connected channels list with its channel name, subscriber count, and connection status.</li>
      </ol>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Each channel's OAuth tokens are stored independently and encrypted at rest. Tokens are refreshed
        automatically when they expire. You can disconnect any channel individually without affecting others.
      </p>
      <Warning>
        The YouTube Data API v3 has a daily upload quota (10,000 units per project by default). Each upload consumes approximately 1,600 units. If you are managing many channels under one Google Cloud project, consider requesting a quota increase.
      </Warning>

      <SubHeading id="multi-channel-assign" title="Assigning Channels to Series" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Open any series and go to the <strong className="text-txt-primary">Upload Settings</strong> tab.
        Select a connected YouTube channel from the <strong className="text-txt-primary">Default Channel</strong>
        dropdown. All episodes in this series will upload to the selected channel by default. Individual
        episodes can override this channel selection in their own upload dialog.
      </p>
      <Tip>
        Create one series per YouTube channel/niche to keep content and settings organized. The series bible, voice profile, and visual style will stay consistent across all episodes on that channel.
      </Tip>

      <SubHeading id="multi-channel-schedule" title="Scheduled Publishing" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        When uploading a video, set a <strong className="text-txt-primary">Publish At</strong> datetime to
        schedule the video as a YouTube Premier or to release it at a specific time. The video is uploaded
        immediately but stays private until the scheduled time, at which point YouTube automatically makes
        it public.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Scheduled uploads are shown in the episode's Upload History with their scheduled publish time and
        current YouTube status. The app polls the YouTube API periodically to update status.
      </p>
      <InfoBox>
        Scheduled publishing uses YouTube's native scheduling — the video is uploaded to YouTube servers immediately. You do not need to keep the app running until the scheduled time.
      </InfoBox>
    </section>
  );
}

export default MultiChannel;
