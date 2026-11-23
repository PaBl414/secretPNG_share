"""Minimal rectangular expansion with replicated edges."""

from PIL import Image

from .capacity import MAX_PIXELS, MAX_SIDE, Size, ceildiv, valid_size
from .errors import AppError, LIMIT


def fit_cover(size: Size, required: int, allow_pad: bool) -> Size:
    """Choose the smallest permitted area with deterministic ties."""
    old_width, old_height = size
    if not valid_size(size):
        raise AppError(5, LIMIT)
    if old_width * old_height >= required:
        return size
    if not allow_pad:
        raise AppError(5, "Cover is too small with --no-pad.")
    if required > MAX_PIXELS:
        raise AppError(5, LIMIT)

    best_score = None
    best_size = None
    for width in range(old_width, min(MAX_SIDE, MAX_PIXELS // old_height) + 1):
        height = max(old_height, ceildiv(required, width))
        if not valid_size((width, height)):
            continue
        score = width * height, abs(width * old_height - height * old_width), width - old_width, width
        if best_score is None or score < best_score:
            best_score, best_size = score, (width, height)
    if best_size is None:
        raise AppError(5, LIMIT)
    return best_size


def pad_edge(image: Image.Image, size: Size) -> Image.Image:
    """Extend the right and bottom using copies of the edge samples."""
    old_width, old_height = image.size
    width, height = size
    if size == image.size:
        return image
    output = Image.new(image.mode, size)
    output.paste(image, (0, 0))
    if width > old_width:
        with image.crop((old_width - 1, 0, old_width, old_height)) as edge:
            with edge.resize((width - old_width, old_height), Image.Resampling.NEAREST) as right:
                output.paste(right, (old_width, 0))
    if height > old_height:
        with output.crop((0, old_height - 1, width, old_height)) as edge:
            with edge.resize((width, height - old_height), Image.Resampling.NEAREST) as bottom:
                output.paste(bottom, (0, old_height))
    return output
