from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps


_sessions = {}
_lock = threading.Lock()


def _session(model: str):
    # Load CUDA/cuDNN DLLs shipped in this venv before rembg creates its
    # ONNX session. This keeps the installation self-contained on Windows.
    import onnxruntime as ort
    if hasattr(ort, "preload_dlls"):
        ort.preload_dlls(directory="")
    from rembg import new_session
    with _lock:
        if model not in _sessions:
            _sessions[model] = new_session(model)
        return _sessions[model]


def decontaminate_edges(image: Image.Image, strength: int = 80) -> Image.Image:
    """Use nearby opaque foreground colors to replace background-polluted edge RGB."""
    rgba = image.convert("RGBA")
    array = np.asarray(rgba, dtype=np.float32)
    alpha = array[..., 3] / 255.0
    if strength <= 0 or not np.any((alpha > 0.0) & (alpha < 1.0)):
        return rgba

    weight = Image.fromarray(np.uint8(np.clip(alpha ** 3 * 255.0, 0, 255)), "L")
    smooth_weight = np.asarray(weight.filter(ImageFilter.GaussianBlur(4.0)), dtype=np.float32) / 255.0
    estimated = np.zeros_like(array[..., :3])
    for channel in range(3):
        weighted = Image.fromarray(
            np.uint8(np.clip(array[..., channel] * (alpha ** 3), 0, 255)), "L")
        blurred = np.asarray(weighted.filter(ImageFilter.GaussianBlur(4.0)), dtype=np.float32)
        estimated[..., channel] = blurred / np.maximum(smooth_weight, 1e-4)

    edge = np.clip((1.0 - alpha) * (strength / 100.0), 0.0, 1.0)
    edge[(alpha <= 0.0) | (alpha >= 0.995)] = 0.0
    array[..., :3] = array[..., :3] * (1.0 - edge[..., None]) + estimated * edge[..., None]
    array[..., :3] = np.clip(array[..., :3], 0, 255)
    return Image.fromarray(array.astype(np.uint8), "RGBA")


def refine_alpha(image: Image.Image, shrink: int = 1, feather: float = 0.4) -> Image.Image:
    rgba = image.convert("RGBA")
    rgb = rgba.convert("RGB")
    alpha = rgba.getchannel("A")
    if shrink > 0:
        alpha = alpha.filter(ImageFilter.MinFilter(shrink * 2 + 1))
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(float(feather)))
    rgb.putalpha(alpha)
    return rgb


def remove_background(src: Path, model: str = "birefnet-general",
                      decontaminate: int = 80, shrink: int = 1,
                      feather: float = 0.4) -> Image.Image:
    from rembg import remove
    src = Path(src)
    with Image.open(src) as opened:
        original = ImageOps.exif_transpose(opened).convert("RGBA")
    result = remove(original, session=_session(model))
    if not isinstance(result, Image.Image):
        from io import BytesIO
        result = Image.open(BytesIO(result)).convert("RGBA")
    result = decontaminate_edges(result, decontaminate)
    return refine_alpha(result, shrink, feather)


def save_outputs(result: Image.Image, src: Path, transparent=True,
                 white=True, black_preview=False, output_dir=None):
    src = Path(src)
    root = Path(output_dir) if output_dir else src.parent / f"{src.stem}_抠图"
    root.mkdir(parents=True, exist_ok=True)
    outputs = []
    if transparent:
        path = root / f"{src.stem}_透明.png"
        result.save(path, "PNG", optimize=True)
        outputs.append(path)
    for enabled, color, suffix in (
        (white, (255, 255, 255, 255), "白底"),
        (black_preview, (0, 0, 0, 255), "黑底预览"),
    ):
        if enabled:
            background = Image.new("RGBA", result.size, color)
            composed = Image.alpha_composite(background, result).convert("RGB")
            path = root / f"{src.stem}_{suffix}.jpg"
            composed.save(path, "JPEG", quality=96, subsampling=0, optimize=True)
            outputs.append(path)
    return outputs
