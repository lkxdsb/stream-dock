from __future__ import annotations

from pathlib import Path


def _require_pillow():
    try:
        from PIL import Image, ImageSequence  # type: ignore
        return Image, ImageSequence
    except Exception as exc:  # pragma: no cover
        raise RuntimeError('缺少 Pillow，无法处理图片转换') from exc


def convert_image(source: str, target: str, input_path: Path, output_path: Path) -> list[str]:
    Image, ImageSequence = _require_pillow()
    logs = [f'打开图片：{input_path.name}']
    target_format = {
        'jpg': 'JPEG',
        'jpeg': 'JPEG',
        'tiff': 'TIFF',
        'ico': 'ICO',
        'ppm': 'PPM',
        'pgm': 'PPM',
        'pbm': 'PPM',
        'pnm': 'PPM',
    }.get(target, target.upper())

    with Image.open(input_path) as image:
        if source == 'gif' and target == 'png':
            output_path.mkdir(parents=True, exist_ok=True)
            for index, frame in enumerate(ImageSequence.Iterator(image)):
                frame.convert('RGBA').save(output_path / f'frame_{index + 1:04d}.png')
            return logs + [f'GIF 已导出为 {index + 1} 张 PNG']

        if target == 'gif' and source == 'png':
            # Single PNG to GIF fallback. Sequence support can be added with folder input later.
            image.save(output_path, format='GIF')
            return logs + ['PNG 已转换为 GIF']

        if source == 'gif':
            raise RuntimeError(f'GIF 不支持转换为 {target.upper()}，请导出为 PNG 帧序列')

        converted = image
        if target in {'jpg', 'jpeg'}:
            if image.mode in {'RGBA', 'LA', 'P'}:
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    converted = image.convert('RGBA')
                background.paste(converted, mask=converted.getchannel('A') if converted.mode in {'RGBA', 'LA'} else None)
                converted = background
            else:
                converted = image.convert('RGB')
        elif target in {'png', 'webp', 'bmp', 'tiff', 'ico'}:
            converted = image.convert('RGBA') if image.mode in {'P', 'LA'} else image
        elif target in {'ppm', 'pnm'}:
            converted = image.convert('RGB')
        elif target == 'pgm':
            converted = image.convert('L')
        elif target == 'pbm':
            converted = image.convert('1')
        converted.save(output_path, format=target_format)
        return logs + [f'图片已转换为 {target.upper()}']
