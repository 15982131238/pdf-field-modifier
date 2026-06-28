#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
verify_output.py — 验证修改后的 PDF 视觉效果

用法:
    python verify_output.py <output.pdf> <verify_dir> [--config candidates.json]

输出:
    verify_dir/page_<N>.png  每页预览
    verify_dir/zoom_<id>.png  每个修改字段 200% 放大图
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
    from PIL import Image
except ImportError as e:
    print(f"缺少依赖: {e}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='验证修改后的 PDF 视觉效果')
    parser.add_argument('output_pdf', help='要验证的 PDF 路径')
    parser.add_argument('verify_dir', help='验证图输出目录')
    parser.add_argument('--config', help='字段配置 JSON (用于放大显示每个字段)')
    parser.add_argument('--scale', type=int, default=3, help='渲染缩放 (默认 3)')
    args = parser.parse_args()

    if not os.path.exists(args.output_pdf):
        print(f"PDF 不存在: {args.output_pdf}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.verify_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf = pdfium.PdfDocument(args.output_pdf)
    print(f"PDF: {args.output_pdf} ({len(pdf)} 页)")

    # 渲染每页
    for i in range(len(pdf)):
        img = pdf[i].render(scale=args.scale).to_pil().convert('RGB')
        out_path = out_dir / f"page_{i+1}.png"
        img.save(out_path)
        print(f"  page {i+1}: {out_path}")

    # 如果有 config, 放大每个修改字段
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)
        candidates = config.get('candidates', [])

        pdf4 = pdfium.PdfDocument(args.output_pdf)
        for c in candidates:
            if not c.get('new_value'):
                continue
            page_idx = c['page']
            img = pdf4[page_idx].render(scale=4).to_pil().convert('RGB')

            val = c['value_above']
            line = c['underline']
            x1 = max(0, val['x_left'] - 100)
            y1 = max(0, val['y_top'] - 30)
            x2 = min(img.width, val['x_right'] + 100)
            y2 = min(img.height, line['y'] + 30)

            crop = img.crop((x1, y1, x2, y2))
            crop_large = crop.resize((crop.width * 2, crop.height * 2))
            out_path = out_dir / f"zoom_{c['id']}_{c['new_value']}.png"
            crop_large.save(out_path)
            print(f"  zoom: {out_path}")
        pdf4.close()

    pdf.close()
    print(f"\n完成。请打开 {out_dir} 查看每页和每个字段的放大图, 确认:")
    print("  1. 新值在原字段字位置 (不飘、不被切)")
    print("  2. 下划线保住")
    print("  3. 字号跟周围中文字号匹配")


if __name__ == '__main__':
    main()