from pathlib import Path

from PIL import Image, ImageDraw


def _draw_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = max(2, int(size * 0.03))
    draw.ellipse(
        (margin, margin, size - margin - 1, size - margin - 1),
        fill=(60, 120, 194, 255),
    )

    fg = (255, 255, 255, 255)

    capsule_left = int(size * 0.34)
    capsule_top = int(size * 0.16)
    capsule_right = int(size * 0.66)
    capsule_bottom = int(size * 0.63)
    capsule_radius = max(2, int(size * 0.16))
    draw.rounded_rectangle(
        (capsule_left, capsule_top, capsule_right, capsule_bottom),
        radius=capsule_radius,
        fill=fg,
    )

    stem_left = int(size * 0.42)
    stem_top = int(size * 0.63)
    stem_right = int(size * 0.58)
    stem_bottom = int(size * 0.84)
    stem_radius = max(1, int(size * 0.05))
    draw.rounded_rectangle(
        (stem_left, stem_top, stem_right, stem_bottom),
        radius=stem_radius,
        fill=fg,
    )

    base_left = int(size * 0.31)
    base_top = int(size * 0.86)
    base_right = int(size * 0.69)
    base_bottom = int(size * 0.95)
    base_radius = max(1, int(size * 0.05))
    draw.rounded_rectangle(
        (base_left, base_top, base_right, base_bottom),
        radius=base_radius,
        fill=fg,
    )

    return image


def main() -> None:
    out_path = Path("src") / "smolstt.ico"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = _draw_icon(256)
    base.save(
        out_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
