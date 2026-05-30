# Marketing preview videos

Drop preview clips here using the exact filenames listed in
`../images/README.md`. Each video slot on the site points at its file via
a `data-video` attribute and `site.js` loads it automatically once it
exists — no HTML edit needed. Until then the slot shows a labelled
placeholder with a play button.

Expected files:

| Filename            | Target size | Where it appears                                             |
|---------------------|-------------|-------------------------------------------------------------|
| `workflow-demo.mp4` | 1920 × 1080 | Homepage "How it works" — a topic becomes a finished video  |

MP4 (H.264 + AAC), 1080p, a few MB at most. Keep it short (15–40 s).
The poster frame is `../images/workflow-demo-poster.jpg`.
