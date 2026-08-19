"""Pillow-rendered naval graphics for the native Tkinter client."""

from __future__ import annotations

import math
from pathlib import Path
import tkinter as tk
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageTk
except ImportError as exc:  # pragma: no cover - installation-specific
    raise SystemExit(
        "Pillow is not installed. Activate the virtual environment and run: "
        "python -m pip install -r requirements.txt"
    ) from exc


CYAN = "#51e1dc"
CYAN_DARK = "#17454b"
ORANGE = "#ff754c"
YELLOW = "#f4c95d"
MUTED = "#8aa4b4"
SHIP_ASSETS = Path(__file__).with_name("assets") / "ships"
BATTLEFIELD_ASSET = Path(__file__).with_name("assets") / "backgrounds" / "pearl_harbor.png"


class NavalIcons:
    """Create and cache small transparent PhotoImages used by board buttons."""

    def __init__(self, master: tk.Misc, cell_size: int = 28) -> None:
        self.master = master
        self.cell_size = cell_size
        self.cache: dict[tuple[Any, ...], ImageTk.PhotoImage] = {}
        self.sources: dict[str, Image.Image] = {}
        self.battlefield = self._load_battlefield()

    def _photo(self, key: tuple[Any, ...], image: Image.Image) -> ImageTk.PhotoImage:
        if key not in self.cache:
            self.cache[key] = ImageTk.PhotoImage(image, master=self.master)
        return self.cache[key]

    def ship_segment(
        self,
        name: str,
        orientation: str,
        index: int,
        length: int,
        hit: bool = False,
        row: int | None = None,
        column: int | None = None,
    ) -> ImageTk.PhotoImage:
        key = ("real-segment", name, orientation, index, length, hit, row, column)
        if key in self.cache:
            return self.cache[key]
        source = self._source(name)
        if source is not None:
            image = self._real_ship_segment(source, orientation, index, length, hit)
            image = self._on_battlefield(image, row, column)
            return self._photo(key, image)
        return self._vector_ship_segment(name, orientation, index, length, hit)

    def _source(self, name: str) -> Image.Image | None:
        if name in self.sources:
            return self.sources[name]
        path = SHIP_ASSETS / f"{name.casefold()}.png"
        if not path.exists():
            return None
        image = Image.open(path).convert("RGBA")
        bounding_box = image.getchannel("A").getbbox()
        if bounding_box:
            image = image.crop(bounding_box)
        image = ImageEnhance.Contrast(image).enhance(1.08)
        image = ImageEnhance.Sharpness(image).enhance(1.25)
        self.sources[name] = image
        return image

    def _fit_ship(self, source: Image.Image, width: int, height: int, glow: bool = True) -> Image.Image:
        scale = min((width - 4) / source.width, (height - 4) / source.height)
        resized = source.resize(
            (max(1, int(source.width * scale)), max(1, int(source.height * scale))),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        x = (width - resized.width) // 2
        y = (height - resized.height) // 2
        if glow:
            alpha = resized.getchannel("A").filter(ImageFilter.MaxFilter(3)).point(
                lambda value: int(value * 0.45)
            )
            glow_layer = Image.new("RGBA", resized.size, CYAN)
            glow_layer.putalpha(alpha)
            canvas.alpha_composite(glow_layer, (x, y))
        canvas.alpha_composite(resized, (x, y))
        return canvas

    def _real_ship_segment(
        self,
        source: Image.Image,
        orientation: str,
        index: int,
        length: int,
        hit: bool,
    ) -> Image.Image:
        size = self.cell_size
        full_ship = self._fit_ship(source, size * length, size)
        if orientation == "vertical":
            full_ship = full_ship.rotate(-90, expand=True)
            image = full_ship.crop((0, index * size, size, (index + 1) * size))
        else:
            image = full_ship.crop((index * size, 0, (index + 1) * size, size))
        if hit:
            self._draw_explosion(ImageDraw.Draw(image), size // 2, size // 2, 9)
        return image

    def _vector_ship_segment(
        self,
        name: str,
        orientation: str,
        index: int,
        length: int,
        hit: bool,
    ) -> ImageTk.PhotoImage:
        key = ("vector-segment", name, orientation, index, length, hit)
        if key in self.cache:
            return self.cache[key]
        size = self.cell_size
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        middle_top, middle_bottom = 7, size - 7
        if index == 0:
            hull = [(2, size // 2), (8, middle_top), (size, middle_top), (size, middle_bottom), (8, middle_bottom)]
        elif index == length - 1:
            hull = [(0, middle_top), (size - 7, middle_top), (size - 2, size // 2), (size - 7, middle_bottom), (0, middle_bottom)]
        else:
            hull = [(0, middle_top), (size, middle_top), (size, middle_bottom), (0, middle_bottom)]
        draw.polygon(hull, fill=CYAN_DARK, outline=CYAN)
        draw.line((4, size // 2, size - 4, size // 2), fill=CYAN, width=1)
        if 0 < index < length - 1:
            draw.ellipse((size // 2 - 3, size // 2 - 3, size // 2 + 3, size // 2 + 3), fill=CYAN)
        if hit:
            self._draw_explosion(draw, size // 2, size // 2, 9)
        if orientation == "vertical":
            image = image.rotate(90, expand=False)
        return self._photo(key, image)

    def _load_battlefield(self) -> Image.Image | None:
        if not BATTLEFIELD_ASSET.exists():
            return None
        size = self.cell_size * 10
        image = Image.open(BATTLEFIELD_ASSET).convert("RGB")
        image = ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
        image = ImageEnhance.Brightness(image).enhance(0.72)
        image = ImageEnhance.Color(image).enhance(0.82)
        return image.convert("RGBA")

    def _battlefield_cell(self, row: int | None, column: int | None) -> Image.Image:
        size = self.cell_size
        if self.battlefield is None or row is None or column is None:
            return Image.new("RGBA", (size, size), "#123142")
        return self.battlefield.crop(
            (column * size, row * size, (column + 1) * size, (row + 1) * size)
        )

    def _on_battlefield(
        self, foreground: Image.Image, row: int | None, column: int | None
    ) -> Image.Image:
        background = self._battlefield_cell(row, column)
        background.alpha_composite(foreground)
        return background

    def fleet_ship(self, name: str, length: int, selected: bool = False) -> ImageTk.PhotoImage:
        key = ("real-fleet", name, length, selected)
        if key in self.cache:
            return self.cache[key]
        width, height = 18 * length, 20
        source = self._source(name)
        if source is not None:
            image = self._fit_ship(source, width, height, glow=selected)
            return self._photo(key, image)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        color = CYAN if selected else MUTED
        hull = [(2, 10), (10, 4), (width - 9, 4), (width - 2, 10), (width - 9, 16), (10, 16)]
        draw.polygon(hull, fill=CYAN_DARK, outline=color)
        draw.rectangle((width // 2 - 6, 1, width // 2 + 5, 9), fill=CYAN_DARK, outline=color)
        draw.line((5, 10, width - 5, 10), fill=color, width=1)
        return self._photo(key, image)

    def team_flag(
        self,
        team: str,
        width: int = 112,
        height: int = 64,
        selected: bool = False,
    ) -> ImageTk.PhotoImage:
        """Render crisp US and Japan flags for native command cards."""
        key = ("team-flag", team, width, height, selected)
        if key in self.cache:
            return self.cache[key]

        border = 3
        image = Image.new("RGBA", (width, height), "#071116")
        draw = ImageDraw.Draw(image)
        x0, y0 = border, border
        x1, y1 = width - border - 1, height - border - 1
        flag_width = x1 - x0 + 1
        flag_height = y1 - y0 + 1

        if team == "US":
            stripe_height = flag_height / 13
            for stripe in range(13):
                top = y0 + round(stripe * stripe_height)
                bottom = y0 + round((stripe + 1) * stripe_height) - 1
                color = "#b22234" if stripe % 2 == 0 else "#f4f4ef"
                draw.rectangle((x0, top, x1, bottom), fill=color)
            canton_width = round(flag_width * 0.40)
            canton_height = round(stripe_height * 7)
            draw.rectangle(
                (x0, y0, x0 + canton_width - 1, y0 + canton_height - 1),
                fill="#3c3b6e",
            )
            star_radius = max(1.0, height * 0.012)
            for row in range(9):
                star_count = 6 if row % 2 == 0 else 5
                y = y0 + canton_height * (row + 1) / 10
                for column in range(star_count):
                    x = x0 + canton_width * (column + 0.55) / star_count
                    points = []
                    for point in range(10):
                        angle = -math.pi / 2 + point * math.pi / 5
                        radius = star_radius if point % 2 == 0 else star_radius * 0.42
                        points.append((x + math.cos(angle) * radius, y + math.sin(angle) * radius))
                    draw.polygon(points, fill="#ffffff")
        else:
            draw.rectangle((x0, y0, x1, y1), fill="#f7f7f4")
            radius = int(flag_height * 0.30)
            center_x = x0 + flag_width // 2
            center_y = y0 + flag_height // 2
            draw.ellipse(
                (
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                ),
                fill="#bc002d",
            )

        outline = "#d43b36" if selected else "#60737b"
        draw.rectangle((1, 1, width - 2, height - 2), outline=outline, width=2)
        draw.line((3, height - 3, width - 3, height - 3), fill="#020607", width=2)
        draw.line((width - 3, 3, width - 3, height - 3), fill="#020607", width=2)
        return self._photo(key, image)

    def command_map(self, width: int, height: int) -> ImageTk.PhotoImage:
        """Render a dark tactical-menu backdrop from the Pearl Harbor battlefield."""
        key = ("command-map", width, height)
        if key in self.cache:
            return self.cache[key]
        if BATTLEFIELD_ASSET.exists():
            source = Image.open(BATTLEFIELD_ASSET).convert("RGB")
            image = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS)
        else:
            image = Image.new("RGB", (width, height), "#07131f")
        image = ImageEnhance.Brightness(image).enhance(0.38).convert("RGBA")
        image = ImageEnhance.Contrast(image).enhance(1.18)

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for x in range(width):
            strength = int(120 * (1 - x / max(1, width)))
            draw.line((x, 0, x, height), fill=(85, 5, 5, strength))
        for y in range(0, height, 4):
            draw.line((0, y, width, y), fill=(0, 0, 0, 28))
        grid_color = (143, 178, 183, 30)
        for x in range(0, width, 54):
            draw.line((x, 0, x, height), fill=grid_color)
        for y in range(0, height, 54):
            draw.line((0, y, width, y), fill=grid_color)

        radar_x, radar_y = int(width * 0.32), int(height * 0.55)
        for radius in (55, 105, 155):
            draw.ellipse(
                (radar_x - radius, radar_y - radius, radar_x + radius, radar_y + radius),
                outline=(81, 225, 220, 52),
                width=1,
            )
        draw.line((radar_x - 175, radar_y, radar_x + 175, radar_y), fill=(81, 225, 220, 48))
        draw.line((radar_x, radar_y - 175, radar_x, radar_y + 175), fill=(81, 225, 220, 48))
        draw.line((radar_x, radar_y, radar_x + 115, radar_y - 92), fill=(218, 57, 52, 150), width=2)
        draw.rectangle((8, 8, width - 9, height - 9), outline=(139, 164, 174, 85), width=1)
        draw.rectangle((15, 15, width - 16, height - 16), outline=(218, 57, 52, 75), width=1)
        image.alpha_composite(overlay)
        return self._photo(key, image)

    def target(self, row: int | None = None, column: int | None = None) -> ImageTk.PhotoImage:
        key = ("target", row, column)
        if key in self.cache:
            return self.cache[key]
        size = self.cell_size
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((7, 7, size - 8, size - 8), outline=MUTED, width=1)
        draw.ellipse((11, 11, size - 12, size - 12), outline=MUTED, width=1)
        draw.line((size // 2, 3, size // 2, 10), fill=MUTED)
        draw.line((size // 2, size - 10, size // 2, size - 3), fill=MUTED)
        draw.line((3, size // 2, 10, size // 2), fill=MUTED)
        draw.line((size - 10, size // 2, size - 3, size // 2), fill=MUTED)
        return self._photo(key, self._on_battlefield(image, row, column))

    def water(self, row: int | None = None, column: int | None = None) -> ImageTk.PhotoImage:
        key = ("water", row, column)
        if key in self.cache:
            return self.cache[key]
        size = self.cell_size
        if self.battlefield is not None and row is not None and column is not None:
            return self._photo(key, self._battlefield_cell(row, column))
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        water_line = "#244555"
        draw.arc((5, 10, 17, 18), 200, 340, fill=water_line, width=1)
        draw.arc((12, 10, 24, 18), 200, 340, fill=water_line, width=1)
        return self._photo(key, image)

    def hit(self, row: int | None = None, column: int | None = None) -> ImageTk.PhotoImage:
        key = ("hit", row, column)
        if key in self.cache:
            return self.cache[key]
        size = self.cell_size
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        self._draw_explosion(ImageDraw.Draw(image), size // 2, size // 2, 11)
        return self._photo(key, self._on_battlefield(image, row, column))

    def miss(self, row: int | None = None, column: int | None = None) -> ImageTk.PhotoImage:
        key = ("miss", row, column)
        if key in self.cache:
            return self.cache[key]
        size = self.cell_size
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.arc((3, 11, size - 4, size - 3), 200, 340, fill=CYAN, width=2)
        draw.arc((8, 14, size - 9, size - 7), 200, 340, fill=MUTED, width=1)
        draw.polygon(
            [(size // 2, 3), (size // 2 - 4, 11), (size // 2, 14), (size // 2 + 4, 11)],
            fill=CYAN,
        )
        return self._photo(key, self._on_battlefield(image, row, column))

    @staticmethod
    def _draw_explosion(draw: ImageDraw.ImageDraw, center_x: int, center_y: int, radius: int) -> None:
        points = []
        for index in range(16):
            angle = math.pi * index / 8
            distance = radius if index % 2 == 0 else radius * 0.48
            points.append(
                (center_x + math.cos(angle) * distance, center_y + math.sin(angle) * distance)
            )
        draw.polygon(points, fill=ORANGE, outline=YELLOW)
        draw.ellipse((center_x - 3, center_y - 3, center_x + 3, center_y + 3), fill=YELLOW)
