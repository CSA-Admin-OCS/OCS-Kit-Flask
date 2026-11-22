#!/usr/bin/env python3
"""Make the web logo files from the source logo in branding/.

    python scripts/make_logo_assets.py

branding/ocs-backend-logo.png is the logo on a white background. This removes the white (the less white a pixel is,
the more opaque it becomes; solid colours keep their colour) and writes three transparent PNGs into static/assets/:
    ocs_backend_logo.png   the whole wordmark, 1100 px wide (home page, login page, README)
    ocs_backend_mark.png   the flask alone, 256 px square (the navbar logo until an organization sets its own)
    favicon.png            the flask alone, 64 px square
Needs Pillow and numpy, which the app itself does not: this is a one-off design step, and the PNGs are committed.
FLASK_BOX is where the flask sits in the current source (just before the "O"); change it if the source changes.
"""
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, '..', 'branding', 'ocs-backend-logo.png')
ASSETS = os.path.join(HERE, '..', 'static', 'assets')
FLASK_BOX = (60, 255, 484, 650)   # left, top, right, bottom in the source
WORDMARK_WIDTH, MARK_SIZE, FAVICON_SIZE = 1100, 256, 64
WHITE_FLOOR = 8                    # a pixel this close to white or closer is fully transparent


def white_to_alpha(image):
    pixels = np.asarray(image.convert('RGB')).astype('float32')
    alpha = np.clip((255 - pixels.min(axis=2) - WHITE_FLOOR) / (255 - WHITE_FLOOR), 0, 1)
    rgb = 255 - (255 - pixels) / np.maximum(alpha, 1e-4)[..., None]     # un-blend from the white
    return Image.fromarray(np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype('uint8'), 'RGBA')


def visible_box(image):
    return image.getchannel('A').point(lambda value: 255 if value > 25 else 0).getbbox()


def square(image, margin):
    side = max(image.size) + 2 * margin
    tile = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    tile.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return tile


def main():
    logo = white_to_alpha(Image.open(SOURCE))
    left, top, right, bottom = visible_box(logo)
    margin = 24
    wordmark = logo.crop((max(left - margin, 0), max(top - margin, 0), right + margin, bottom + margin))
    wordmark = wordmark.resize((WORDMARK_WIDTH, round(wordmark.height * WORDMARK_WIDTH / wordmark.width)), Image.LANCZOS)
    wordmark.save(os.path.join(ASSETS, 'ocs_backend_logo.png'), optimize=True)

    flask = logo.crop(FLASK_BOX)
    flask = square(flask.crop(visible_box(flask)), margin=14)
    flask.resize((MARK_SIZE, MARK_SIZE), Image.LANCZOS).save(os.path.join(ASSETS, 'ocs_backend_mark.png'), optimize=True)
    flask.resize((FAVICON_SIZE, FAVICON_SIZE), Image.LANCZOS).save(os.path.join(ASSETS, 'favicon.png'), optimize=True)
    print('wrote ocs_backend_logo.png, ocs_backend_mark.png and favicon.png to static/assets/')


if __name__ == '__main__':
    main()
