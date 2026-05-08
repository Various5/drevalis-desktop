import { Youtube } from 'lucide-react';
import { SectionHeading, SubHeading, Tip, InfoBox, Warning } from './_shared';

export function SocialYoutube() {
  return (
    <section id="social-youtube" className="mb-16 scroll-mt-4">
      <SectionHeading id="social-youtube-heading" icon={Youtube} title="Social Media & YouTube" />

      <SubHeading id="connect-youtube" title="Connecting YouTube (OAuth Flow)" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Drevalis Creator Studio uses Google OAuth 2.0 to connect your YouTube channel. The flow requires a Google
        Cloud project with the YouTube Data API v3 enabled.
      </p>
      <div className="space-y-2 text-sm text-txt-secondary leading-relaxed mb-4">
        <p><strong className="text-txt-primary">Prerequisites:</strong></p>
        <ol className="list-decimal list-inside space-y-1.5 ml-3">
          <li>Create a project in the <a href="https://console.cloud.google.com" className="text-accent hover:underline" target="_blank" rel="noreferrer">Google Cloud Console</a></li>
          <li>Enable the YouTube Data API v3 for the project</li>
          <li>Create OAuth 2.0 credentials (type: Web application)</li>
          <li>Add <code className="font-mono text-xs text-accent">http://localhost:8000/api/v1/youtube/callback</code> as an authorized redirect URI</li>
          <li>Copy the Client ID and Client Secret into your <code className="font-mono text-xs text-accent">.env</code> file as <code className="font-mono text-xs text-accent">YOUTUBE_CLIENT_ID</code> and <code className="font-mono text-xs text-accent">YOUTUBE_CLIENT_SECRET</code></li>
          <li>Restart the backend</li>
        </ol>
        <p className="mt-3"><strong className="text-txt-primary">Connect:</strong> Go to Settings → YouTube → Connect Account. You'll be redirected to Google's OAuth consent screen. After granting permissions, you're returned to the app and the channel is connected.</p>
      </div>
      <InfoBox>
        OAuth tokens are encrypted at rest using Fernet encryption. They are never stored or logged in plaintext. The app automatically refreshes expired tokens using the refresh token.
      </InfoBox>

      <SubHeading id="connect-other" title="Connecting TikTok, Instagram, Facebook, and X" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        TikTok offers a full OAuth flow; Instagram, Facebook, and X (Twitter) use platform-specific
        API tokens you paste into <strong className="text-txt-primary">Settings → Social Media</strong>.
        Once connected, videos can be uploaded directly from the episode export menu.
      </p>
      <ul className="text-sm text-txt-secondary leading-relaxed list-disc pl-5 space-y-1.5 mb-3">
        <li>
          <strong className="text-txt-primary">Facebook:</strong> needs a Page Access Token
          <em> (not a user token)</em> plus the numeric Page ID. Drevalis validates both at
          connect-time and will refuse to save the credential if either is missing.
        </li>
        <li>
          <strong className="text-txt-primary">Instagram:</strong> needs a Business/Creator
          Account ID and a public HTTPS URL that maps to your storage folder — Reels require the
          video to be reachable over the internet. Both fields are enforced at connect-time.
        </li>
        <li>
          <strong className="text-txt-primary">X (Twitter):</strong> paste an OAuth 2.0 user
          access token with <code>tweet.write</code> + <code>media.write</code> scopes.
        </li>
        <li>
          <strong className="text-txt-primary">TikTok:</strong> click <em>Connect TikTok</em>;
          Drevalis handles the PKCE OAuth round-trip.
        </li>
      </ul>
      <Warning>
        TikTok, Instagram, and Facebook require developer app approval for upload access.
        Standard personal accounts do not have API upload permissions without an approved app
        registration on each platform. X (Twitter) requires paid API access on current tiers.
      </Warning>

      <SubHeading id="uploading" title="Uploading Videos" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        From any episode detail page, open the <strong className="text-txt-primary">Export</strong> dropdown
        and select <strong className="text-txt-primary">Upload to YouTube</strong>. An upload dialog
        pre-fills the video title, description, and tags from the episode script. You can edit these before
        uploading.
      </p>
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The description is formatted for YouTube with the episode summary, keywords as hashtags, and a
        generated call-to-action. The export bundle (ZIP) includes the MP4 video, thumbnail JPEG, and
        description text file.
      </p>

      <SubHeading id="playlists" title="Playlists" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        Episodes from the same series can be automatically added to a YouTube playlist. Set the playlist ID
        in the series settings. All future uploads from that series will be added to the playlist.
      </p>

      <SubHeading id="privacy" title="Privacy Settings" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        {[
          { level: 'Private', desc: 'Only you can see the video. Default for all uploads.' },
          { level: 'Unlisted', desc: 'Anyone with the link can see it. Not searchable.' },
          { level: 'Public', desc: 'Visible to everyone. Indexed by YouTube search.' },
        ].map(item => (
          <div key={item.level} className="surface p-3 rounded-lg text-center">
            <p className="text-sm font-semibold text-txt-primary mb-1">{item.level}</p>
            <p className="text-xs text-txt-secondary">{item.desc}</p>
          </div>
        ))}
      </div>
      <Tip>
        Upload as Private first, verify the video looks correct in YouTube Studio, then change to Public manually. This avoids publishing videos with issues.
      </Tip>

    </section>
  );
}

export default SocialYoutube;
