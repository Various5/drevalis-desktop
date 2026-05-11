# Marketing image slots

Drop the final screenshots / graphics into this directory using the
**exact filenames** listed below. Until a file exists, the page shows
a dashed placeholder card with the filename + target dimensions written
inside it, so you can see at a glance which slot is empty.

The site doesn't need a rebuild when you add images — Nginx serves them
directly out of the mounted volume. But since our deploy uses a baked
image (`drevalis-site:local` built from this tree), you'll need to
rebuild + restart the container after adding files. That's one command:

```bash
# From the VPS, in /srv/drevalis-site:
docker compose up -d --build
```

## Image inventory

| Filename                               | Target size | Where it appears                                      |
|----------------------------------------|-------------|-------------------------------------------------------|
| `hero-dashboard.png`                   | 1920 × 1080 | Homepage hero — full dashboard mid-generation         |
| `feature-script-editor.png`            | 1600 × 1200 | Homepage feature row 1 — episode script editor        |
| `feature-voice-profiles.png`           | 1600 × 1200 | Homepage feature row 2 — voice profile library        |
| `feature-scene-grid.png`               | 1600 × 1200 | Homepage feature row 3 — scene gallery                |
| `feature-youtube-publish.png`          | 1600 × 1200 | Homepage feature row 4 — YouTube multi-channel picker |
| `workflow-activity-monitor.png`        | 2100 × 900  | Homepage workflow section — activity monitor          |
| `og-cover.png`                         | 1200 × 630  | Open Graph image (social sharing preview)             |

## Format notes

- PNG or JPG both work. PNG is preferred for UI screenshots (crisper
  text). JPG for photographic content.
- Keep under ~500 KB each where possible — the site is tiny and we
  want it to stay fast.
- Target sizes are 2× the display size so Retina screens stay sharp.
  Don't exceed 2500 px on the long edge.
- Frame at the exact aspect ratio shown in the table. The slot will
  `object-fit: cover` so off-ratio images get cropped.

## If you want to swap a slot for a video

Each image tag lives inside a `<div class="img-slot">` in the HTML.
To use a video instead, replace the `<img ...>` with:

```html
<video src="/assets/images/hero-demo.mp4" autoplay loop muted playsinline>
</video>
```

The existing CSS already styles `<video>` inside `.img-slot` the
same as images.
