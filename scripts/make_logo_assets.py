#!/usr/bin/env python3
"""Make the web logo files from the source logos in branding/.

    python scripts/make_logo_assets.py

There are two sources: branding/ocs-backend-logo.png is the logo made for a light background (on white), and
branding/ocs-backend-logo-dark.png is the one made for a dark background (glowing on black). Each has its background
removed and is written as a transparent PNG into static/assets/:
    ocs_backend_logo.png        the whole wordmark for light pages, 1100 px wide (home, login, README)
    ocs_backend_logo_dark.png   the whole wordmark for dark pages, 1100 px wide (shown instead in dark mode)
    ocs_backend_mark.png        the flask alone, 256 px square (the navbar logo until an organization sets its own)
    favicon.png                 the flask alone, 64 px square
The light source loses its white (the less white a pixel is, the more opaque it becomes; solid colours keep their
colour). The dark source loses its black and the glow around it (pixels darker than DARK_LOW vanish, brighter than
DARK_HIGH are solid, and the edge between is soft).
Needs Pillow and numpy, which the app itself does not: this is a one-off design step, and the PNGs are committed.
FLASK_BOX is where the flask sits in the light source (just before the "O"); change it if that source changes.
"""
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, '..', 'branding', 'ocs-backend-logo.png')
DARK_SOURCE = os.path.join(HERE, '..', 'branding', 'ocs-backend-logo-dark.png')
ASSETS = os.path.join(HERE, '..', 'static', 'assets')
FLASK_BOX = (60, 255, 484, 650)   # left, top, right, bottom in the source
WORDMARK_WIDTH, MARK_SIZE, FAVICON_SIZE = 1100, 256, 64
WHITE_FLOOR = 8                    # a pixel this close to white or closer is fully transparent
DARK_LOW, DARK_HIGH = 0.35, 0.60   # brightness below which the dark source is transparent, and above which it is solid


def white_to_alpha(image):
    pixels = np.asarray(image.convert('RGB')).astype('float32')
    alpha = np.clip((255 - pixels.min(axis=2) - WHITE_FLOOR) / (255 - WHITE_FLOOR), 0, 1)
    rgb = 255 - (255 - pixels) / np.maximum(alpha, 1e-4)[..., None]     # un-blend from the white
    return Image.fromarray(np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype('uint8'), 'RGBA')


def black_to_alpha(image):
    pixels = np.asarray(image.convert('RGB')).astype('float32') / 255.0
    brightness = pixels.max(axis=2)
    t = np.clip((brightness - DARK_LOW) / (DARK_HIGH - DARK_LOW), 0, 1)
    alpha = t * t * (3 - 2 * t)                                                    # smoothstep
    rgb = np.clip(pixels / np.maximum(brightness, 1e-4)[..., None] * np.maximum(brightness, 0.55)[..., None], 0, 1)
    return Image.fromarray((np.dstack([rgb, alpha]) * 255).astype('uint8'), 'RGBA')


def visible_box(image):
    return image.getchannel('A').point(lambda value: 255 if value > 25 else 0).getbbox()


def square(image, margin):
    side = max(image.size) + 2 * margin
    tile = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    tile.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return tile


def wordmark(logo):
    left, top, right, bottom = visible_box(logo)
    margin = 24
    crop = logo.crop((max(left - margin, 0), max(top - margin, 0), right + margin, bottom + margin))
    return crop.resize((WORDMARK_WIDTH, round(crop.height * WORDMARK_WIDTH / crop.width)), Image.LANCZOS)


def main():
    logo = white_to_alpha(Image.open(SOURCE))
    wordmark(logo).save(os.path.join(ASSETS, 'ocs_backend_logo.png'), optimize=True)
    wordmark(black_to_alpha(Image.open(DARK_SOURCE))).save(os.path.join(ASSETS, 'ocs_backend_logo_dark.png'), optimize=True)

    flask = logo.crop(FLASK_BOX)
    flask = square(flask.crop(visible_box(flask)), margin=14)
    flask.resize((MARK_SIZE, MARK_SIZE), Image.LANCZOS).save(os.path.join(ASSETS, 'ocs_backend_mark.png'), optimize=True)
    flask.resize((FAVICON_SIZE, FAVICON_SIZE), Image.LANCZOS).save(os.path.join(ASSETS, 'favicon.png'), optimize=True)
    print('wrote ocs_backend_logo.png, ocs_backend_logo_dark.png, ocs_backend_mark.png and favicon.png to static/assets/')


if __name__ == '__main__':
    main()
