# Marketing media slots

Drop the final screenshots and graphics into this directory using the
**exact filenames** below. You do **not** need to edit any HTML — each
slot already points at its filename via a `data-img` / `data-video`
attribute, and `site.js` loads the file automatically once it exists.

Until a file is present, the page shows a labelled placeholder card (the
filename + target size written inside it), so you can see at a glance
which slot is still empty. Video slots additionally show a play button.

The deploy bakes these files into the `drevalis-site` image, so after
adding or replacing media you rebuild + restart the container — one
command, from `/srv/drevalis-site` on the VPS:

```bash
docker compose up -d --build
```

## Images

| Filename                      | Target size | Where it appears                                   |
|-------------------------------|-------------|----------------------------------------------------|
| `hero-dashboard.png`          | 1920 × 1080 | Homepage hero — the app mid-generation             |
| `feature-script-editor.png`   | 1600 × 1200 | Homepage feature row 1 — script editor             |
| `feature-voice-profiles.png`  | 1600 × 1200 | Homepage feature row 2 — voice library             |
| `feature-scene-grid.png`      | 1600 × 1200 | Homepage feature row 3 — scene gallery             |
| `feature-youtube-publish.png` | 1600 × 1200 | Homepage feature row 4 — publishing panel          |
| `workflow-demo-poster.jpg`    | 1920 × 1080 | Poster frame for the workflow video (below)        |
| `og-cover.png`                | 1200 × 630  | Open Graph image (social sharing preview)          |

## Videos

Preview clips live in `../videos/` (a sibling of this folder). Same rule:
drop the file with the exact name and it appears on the next load.

| Filename (in `/assets/videos/`) | Target size | Where it appears                                              |
|---------------------------------|-------------|--------------------------------------------------------------|
| `workflow-demo.mp4`             | 1920 × 1080 | Homepage "How it works" — a topic becomes a finished video   |

## Format notes

- **Images:** PNG or JPG. PNG is preferred for UI screenshots (crisper
  text), JPG for photographic content. Keep each under ~500 KB where you
  can — the site is tiny and we want it to stay fast. Target sizes are
  2× the display size so Retina screens stay sharp; don't exceed 2500 px
  on the long edge. Frame at the exact aspect ratio shown — slots use
  `object-fit: cover`, so off-ratio media gets cropped.
- **Videos:** MP4 (H.264 + AAC) plays everywhere. Aim for 1080p, a few
  MB at most — keep clips short (15–40 s). A `workflow-demo-poster.jpg`
  poster frame shows before the visitor hits play. The slot renders
  native `<video controls>`, so no autoplay surprises.
