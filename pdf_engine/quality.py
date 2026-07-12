from __future__ import annotations

import json
from pathlib import Path


def evaluate_pdf_result(output_dir: Path) -> dict[str, object]:
    markdown_files = list(output_dir.rglob('*.md'))
    json_files = list(output_dir.rglob('*.json'))
    image_files = [path for suffix in ('*.png', '*.jpg', '*.jpeg', '*.webp') for path in output_dir.rglob(suffix)]
    text = '\n'.join(path.read_text(encoding='utf-8', errors='replace') for path in markdown_files)
    replacement_count = text.count('\ufffd')
    non_space = sum(1 for char in text if not char.isspace())
    malformed_json = 0
    for path in json_files:
        try:
            json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, json.JSONDecodeError):
            malformed_json += 1
    warnings: list[str] = []
    if not markdown_files or non_space == 0:
        warnings.append('未生成可读 Markdown 文本')
    if malformed_json:
        warnings.append(f'{malformed_json} 个 JSON 结果无法读取')
    if replacement_count:
        warnings.append(f'检测到 {replacement_count} 个疑似乱码字符')
    score = max(0, 100 - (45 if not markdown_files or non_space == 0 else 0) - malformed_json * 15 - min(replacement_count, 20))
    return {
        'valid': score >= 60,
        'score': score,
        'level': '良好' if score >= 90 else '可用' if score >= 60 else '需要重试',
        'markdownFiles': len(markdown_files),
        'jsonFiles': len(json_files),
        'imageFiles': len(image_files),
        'textCharacters': non_space,
        'replacementCharacters': replacement_count,
        'warnings': warnings,
    }
