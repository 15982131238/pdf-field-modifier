#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
render_preview.py — 渲染 PDF 为 PNG 预览图（用于手动检查字段位置）

用法:
    python render_preview.py <input.pdf> <output_dir> [--scale 4]

输出:
    output_dir/page_<N>.png  每页一张 PNG
"""

import argparse
import os
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    print("缺少依赖: pip install pypdfium2 pillow", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='把 PDF 渲染为 PNG 预览图')
    parser.add_argument('input_pdf', help='输入 PDF 路径')
    parser.add_argument('output_dir', help='输出目录')
    parser.add_argument('--scale', type=int, default=4, help='渲染缩放 (默认 4 = 2382x3368 for A4)')
    args = parser.parse_args()

    if not os.path.exists(args.input_pdf):
        print(f"输入 PDF 不存在: {args.input_pdf}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf = pdfium.PdfDocument(args.input_pdf)
    print(f"PDF: {args.input_pdf} ({len(pdf)} 页)")

    for i in range(len(pdf)):
        img = pdf[i].render(scale=args.scale).to_pil().convert('RGB')
        out_path = out_dir / f"page_{i+1}.png"
        img.save(out_path)
        print(f"  page {i+1}: {out_path} ({img.size})")

    pdf.close()


if __name__ == '__main__':
    main()