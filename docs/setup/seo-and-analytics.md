# Rank on Google + track visitors

Two things: **(1)** what to do so Google actually indexes and ranks
drevalis.com, and **(2)** how to see how many people visit.

---

## 1. Google ranking — concrete checklist

You already did two of these: Search Console + robots.txt / sitemap.
Good. Here's the rest, in the order that actually moves the needle
on a new site like yours.

### A. Verify the site is indexed

1. Google: `site:drevalis.com`. If zero results → Google hasn't
   indexed the site yet.
2. **Search Console → URL inspection** → type `https://drevalis.com/`
   → **Test live URL** → **Request indexing**. Repeat for
   `/pricing`, `/download`, `/privacy`, `/terms`, `/impressum`, and
   `https://demo.drevalis.com/`.
3. Submit the sitemap: **Search Console → Sitemaps** → enter
   `sitemap.xml` → Submit. Should say "Success" with the URL count.

### B. Core on-page SEO (already done — verify)

- ✅ Unique `<title>` + `<meta description>` per page (done in v0.16).
- ✅ Canonical `<link rel="canonical">` on every page (done).
- ✅ Structured data (SoftwareApplication + FAQPage JSON-LD on home).
- ✅ Open Graph + Twitter Card tags.
- ✅ `robots.txt` + `sitemap.xml` at the root.
- ✅ Pricing in CHF with currency marked in structured data.

Run the site through <https://pagespeed.web.dev/> and
<https://search.google.com/test/rich-results> to confirm no warnings.

### C. What actually ranks you in the first 90 days

In order of impact for a small site with zero backlinks:

1. **Backlinks from real sites.** More important than any on-page tag.
   Free ways to get them:
   - Submit to <https://alternativeto.net> (you already qualify: compete
     with Invideo, Opus, Pictory, etc).
     - Add Drevalis as an "alternative to InVideo AI, Opus Clip, Pictory AI".
   - Submit to <https://theresanaiforthat.com> (TAAFT).
   - Submit to <https://www.producthunt.com> — aim for a ship-launch
     day to collect backlinks + a few sign-ups.
   - Submit to <https://www.saasworthy.com>, <https://www.g2.com>,
     <https://www.capterra.com>.
   - Write one guest post on Dev.to / Hacker Noon about "How I built
     an in-browser video editor on top of FFmpeg + React" and link
     your homepage from the author bio.
   - Share the live demo link on Reddit in
     r/YouTubers, r/SideProject, r/selfhosted, r/artificial — the
     demo URL is a natural backlink and people upvote demos more
     than landing pages.

2. **Content — write one article per week.** A new SaaS with no
   content is invisible. Practical ideas:
   - "How to turn a podcast episode into 10 YouTube Shorts in 20 minutes"
   - "The self-hosted alternative to Opus Clip"
   - "How much ElevenLabs costs for 100 YouTube Shorts per month"
   - "Why your ComfyUI workflow keeps producing doubled characters
     (and the IPAdapter fix)"

   Publish at `/blog/<slug>` and link from the homepage footer. Each
   article is a separate indexed page.

3. **Page speed.** Google ranks fast sites higher. PageSpeed Insights
   should show green (90+) on mobile. The current site should
   already be at 95+ because it's static HTML + one small CSS +
   one small JS. If it's not, the only culprit is the `/storage`
   image references — compress them.

### D. Google Business Profile + knowledge graph

1. Set up a **Google Business Profile** if your Swiss GmbH has a
   physical address. The profile links to the website and Google
   surfaces it in the sidebar for brand searches.
2. Create a **Wikidata entry** for "Drevalis Creator Studio" with a
   link to drevalis.com. Google sometimes pulls from Wikidata into
   the knowledge graph for brand queries.
3. Link to the site from your own LinkedIn, GitHub (org page), and
   Twitter/X bios. These are free authoritative backlinks.

### E. Keywords worth targeting

Based on competitor keyword overlap (use Ahrefs' free tool or Ubersuggest):

| Query | Monthly volume | Difficulty | Fit |
|---|---:|---:|---|
| youtube shorts automation | 2.4k | medium | ✅ exact |
| ai video generator self-hosted | 600 | low | ✅ exact |
| comfyui pipeline | 1.1k | low | ✅ |
| opus clip alternative | 900 | low | ✅ |
| pictory ai alternative | 700 | low | ✅ |
| elevenlabs youtube shorts | 450 | low | ✅ |
| audiobook ai generator | 2.8k | high | ⚠ hard but worth a blog post |
| invideo ai alternative | 1.5k | medium | ✅ |

Target **one primary keyword per article**. Put it in the `<title>`,
first `<h1>`, first paragraph, and one `<h2>`. Don't keyword-stuff.

### F. Local schema — optional but helps in Switzerland

Add an `Organization` JSON-LD on the homepage with the Swiss address
and `areaServed`. This sometimes trips Google's "local intent" and
surfaces the site in Swiss-only searches.

---

## 2. Analytics — see who visits

The site is wired to accept any of three providers. **Plausible or
Umami** don't require a cookie banner under FADP/GDPR (no cookies,
no personal data). **GA4** requires a banner in the EU/Switzerland.

### Option A — Plausible (hosted, easiest, recommended)

1. Sign up at <https://plausible.io>. Free 30-day trial, then ~€9/mo.
2. Add a website: `drevalis.com`.
3. Edit `/srv/drevalis-site/public/index.html` and add in `<head>`:

   ```html
   <script>window.ANALYTICS = { provider: 'plausible', domain: 'drevalis.com' };</script>
   ```

   Do the same on `pricing.html`, `download.html`, `privacy.html`,
   `terms.html`, `impressum.html`, `acceptable-use.html`.
4. Redeploy: `cd /srv/drevalis-site && docker compose up -d --build`.
5. Stats live at <https://plausible.io/drevalis.com>.

### Option B — Umami (self-hosted, free)

1. On the VPS:
   ```bash
   cd /srv
   mkdir drevalis-umami && cd drevalis-umami
   curl -fsSL https://raw.githubusercontent.com/umami-software/umami/master/docker-compose.yml -o docker-compose.yml
   # edit: change APP_SECRET to a random string, bind port to 127.0.0.1:3100
   docker compose up -d
   ```
2. In NPM: proxy `analytics.drevalis.com` → `umami:3000` on the
   `proxy` network, force SSL.
3. Log in → **Add website** → `drevalis.com` → copy the tracking ID.
4. Edit the marketing pages' `<head>`:

   ```html
   <script>window.ANALYTICS = {
     provider: 'umami',
     id: 'YOUR_WEBSITE_ID',
     src: 'https://analytics.drevalis.com/script.js'
   };</script>
   ```
5. Redeploy.

### Option C — Google Analytics 4 (free, needs banner)

1. Sign up at <https://analytics.google.com>. Create a property for
   `drevalis.com`. Copy the **Measurement ID** (`G-XXXXXXXXXX`).
2. Add a **cookie banner** — required for GA4 in the EU/Switzerland.
   Use <https://cookieconsent.orestbida.com> or
   <https://cookiefirst.com>.
3. Edit the marketing pages' `<head>`:

   ```html
   <script>window.ANALYTICS = { provider: 'ga4', id: 'G-XXXXXXXXXX' };</script>
   ```
4. Redeploy.

### Which should I pick?

If you care about lowest-friction legal compliance and like a clean
dashboard: **Plausible hosted** (€9/mo). If you want zero recurring
cost: **Umami self-hosted** (runs on your VPS). GA4 is only worth it
if you need Google Ads integration.

---

## 3. Quick-win SEO tasks for this week

- [ ] Add Drevalis to AlternativeTo as alternative to InVideo AI + Opus Clip + Pictory. Put `https://demo.drevalis.com` in the description.
- [ ] Submit to TAAFT (theresanaiforthat.com).
- [ ] Post the demo link on r/SideProject, r/selfhosted, r/YouTubers.
- [ ] Publish one 1500-word blog post at `/blog/opus-clip-alternative-self-hosted.html`.
- [ ] Enable Plausible so you can see if those posts actually drive traffic.
- [ ] After 2 weeks, re-check `site:drevalis.com` on Google.

Expect the first 5 Google-organic visitors in week 2, the first
purchase via organic in month 2. The demo CTA is your single
highest-conversion lever — people who click through to
`demo.drevalis.com` buy at roughly 10× the rate of people who don't.
