from pathlib import Path

from PIL import Image

from game import FLEET


SHIP_DIRECTORY = Path(__file__).parents[1] / "assets" / "ships"
BATTLEFIELD = Path(__file__).parents[1] / "assets" / "backgrounds" / "pearl_harbor.png"


def test_every_fleet_class_has_a_transparent_realistic_asset():
    for ship_name in FLEET:
        path = SHIP_DIRECTORY / f"{ship_name.casefold()}.png"
        assert path.is_file(), f"Missing graphical asset for {ship_name}"
        with Image.open(path) as image:
            assert image.mode == "RGBA"
            assert image.width > image.height
            assert image.getchannel("A").getextrema() == (0, 255)


def test_pearl_harbor_battlefield_is_a_square_raster_asset():
    with Image.open(BATTLEFIELD) as image:
        assert image.width == image.height
        assert image.width >= 1024
