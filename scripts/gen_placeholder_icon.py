"""Generate a placeholder icon set for the Tauri shell.

Writes ``tauri/src-tauri/icons/{icon.ico,icon.png,32x32.png,128x128.png,
128x128@2x.png}``. Pure Pillow — no external assets. Replace with a
real brand asset before shipping; this is just enough to unblock
``cargo check`` and a first ``tauri build``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICONS_DIR = Path(__file__).resolve().parents[1] / "tauri" / "src-tauri" / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

# Master canvas at 1024×1024 — downscaled to each target size.
MASTER = 1024
INDIGO = (99, 102, 241, 255)
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)


def _draw_master() -> Image.Image:
    img = Image.new("RGBA", (MASTER, MASTER), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    # Rounded square background — indigo.
    inset = MASTER // 16
    draw.rounded_rectangle(
        [(inset, inset), (MASTER - inset, MASTER - inset)],
        radius=MASTER // 6,
        fill=INDIGO,
    )
    # Big white "D" centred.
    try:
        font = ImageFont.truetype("arialbd.ttf", int(MASTER * 0.62))
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", int(MASTER * 0.62))
        except OSError:
            font = ImageFont.load_default()
    draw.text((MASTER // 2, MASTER // 2 + MASTER // 32), "D", fill=WHITE, anchor="mm", font=font)
    return img


def main() -> int:
    master = _draw_master()
    print(f"writing icons under {ICONS_DIR}")

    # Multi-size .ico (Win resource compiler picks the best size at runtime)
    ico_path = ICONS_DIR / "icon.ico"
    master.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"  {ico_path.name}")

    # PNG variants Tauri's bundler picks up by name.
    for name, dim in (
        ("icon.png", 512),
        ("32x32.png", 32),
        ("128x128.png", 128),
        ("128x128@2x.png", 256),
    ):
        out = ICONS_DIR / name
        master.resize((dim, dim), Image.LANCZOS).save(out, "PNG")
        print(f"  {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
