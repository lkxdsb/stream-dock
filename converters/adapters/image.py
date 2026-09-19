from __future__ import annotations

import os
from pathlib import Path


IMAGE_QUALITY = max(1, min(100, int(os.getenv('STREAMDOCK_IMAGE_QUALITY', '90'))))
MAX_IMAGE_PIXELS = int(os.getenv('STREAMDOCK_MAX_IMAGE_PIXELS', '100000000'))
MAX_IMAGE_FRAMES = int(os.getenv('STREAMDOCK_MAX_IMAGE_FRAMES', '1000'))


def _require_pillow():
    try:
        from PIL import Image, ImageSequence  # type: ignore
        return Image, ImageSequence
    except Exception as exc:  # pragma: no cover
        raise RuntimeError('缺少 Pillow，无法处理图片转换') from exc


def convert_image(source: str, target: str, input_path: Path, output_path: Path, *, quality: int | None = None) -> list[str]:
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
        frame_count = int(getattr(image, 'n_frames', 1) or 1)
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise RuntimeError(f'图片像素数超过安全上限 {MAX_IMAGE_PIXELS}')
        if frame_count > MAX_IMAGE_FRAMES:
            raise RuntimeError(f'图片帧数超过安全上限 {MAX_IMAGE_FRAMES}')
        has_transparency = 'A' in image.getbands() or 'transparency' in image.info
        has_icc = bool(image.info.get('icc_profile'))
        has_exif = bool(image.getexif())
        save_options = {}
        icc_targets = {'jpg', 'jpeg', 'png', 'webp', 'tiff'}
        exif_targets = {'jpg', 'jpeg', 'png', 'webp', 'tiff'}
        if has_icc and target in icc_targets:
            save_options['icc_profile'] = image.info['icc_profile']
        exif = image.getexif()
        if exif and target in exif_targets:
            save_options['exif'] = exif.tobytes()
        if source == 'gif' and target == 'png':
            output_path.mkdir(parents=True, exist_ok=True)
            for index, frame in enumerate(ImageSequence.Iterator(image)):
                frame.convert('RGBA').save(output_path / f'frame_{index + 1:04d}.png')
            return logs + [f'GIF 已导出为 {index + 1} 张 PNG', *(['降级说明：GIF 动画循环/帧时序不写入单张 PNG'] if index else [])]

        if source == 'tiff' and target == 'png' and frame_count > 1:
            frames = [frame.convert('RGBA') for frame in ImageSequence.Iterator(image)]
            duration = image.info.get('duration', 100)
            apng_options = {}
            if save_options.get('icc_profile'):
                apng_options['icc_profile'] = save_options['icc_profile']
            frames[0].save(
                output_path,
                format='PNG',
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,
                **apng_options,
            )
            metadata_logs = []
            if has_icc:
                metadata_logs.append('ICC 色彩配置已保留')
            if has_exif:
                metadata_logs.append('降级说明：多帧 TIFF EXIF 不写入 APNG')
            return logs + [f'多帧 TIFF 已转换为包含 {len(frames)} 帧的 APNG', *metadata_logs]

        if target == 'gif' and source == 'png':
            frames = [frame.convert('RGBA') for frame in ImageSequence.Iterator(image)]
            if len(frames) > 1:
                durations = [frame.info.get('duration', image.info.get('duration', 100)) for frame in ImageSequence.Iterator(image)]
                frames[0].save(
                    output_path,
                    format='GIF',
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=image.info.get('loop', 0),
                    disposal=2,
                )
                downgrade = []
                if has_icc:
                    downgrade.append('降级说明：GIF 无法保留 ICC 色彩配置')
                if has_exif:
                    downgrade.append('降级说明：GIF 无法保留 EXIF')
                if has_transparency:
                    downgrade.append('降级说明：GIF 透明度会量化为单色透明')
                return logs + [f'APNG 已转换为包含 {len(frames)} 帧的 GIF', *downgrade]
            frames[0].save(output_path, format='GIF')
            return logs + ['PNG 已转换为 GIF']

        if source == 'gif':
            raise RuntimeError(f'GIF 不支持转换为 {target.upper()}，请导出为 PNG 帧序列')
        if frame_count > 1:
            raise RuntimeError(f'{source.upper()} 含 {frame_count} 帧，{target.upper()} 当前路径无法完整保留所有帧；请改用 APNG/GIF 或 PNG 帧序列')

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
        effective_quality = IMAGE_QUALITY if quality is None else max(1, min(100, int(quality)))
        if target in {'jpg', 'jpeg', 'webp'}:
            save_options['quality'] = effective_quality
        converted.save(output_path, format=target_format, **save_options)
        metadata = []
        if save_options.get('icc_profile'):
            metadata.append('ICC 色彩配置已保留')
        if save_options.get('exif'):
            metadata.append('EXIF 已保留')
        if target in {'jpg', 'jpeg', 'webp'}:
            metadata.append(f'质量 {effective_quality}')
        if target in {'jpg', 'jpeg'} and image.mode in {'RGBA', 'LA', 'P'}:
            metadata.append('透明通道已合成到白色背景')
        elif has_transparency and target in {'bmp', 'ppm', 'pgm', 'pbm', 'pnm', 'ico'}:
            metadata.append(f'降级说明：{target.upper()} 目标不保证完整透明通道')
        if has_icc and target not in icc_targets:
            metadata.append(f'降级说明：{target.upper()} 无法保留 ICC 色彩配置')
        if has_exif and target not in exif_targets:
            metadata.append(f'降级说明：{target.upper()} 无法保留 EXIF')
        return logs + [f'图片已转换为 {target.upper()}', *metadata]
