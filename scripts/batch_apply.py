#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
batch_apply.py — 批量处理多个相同模板 PDF

用法:
    # 1. 先用一个模板生成 candidates.json
    python modify_pdf_smart.py scan template.pdf > candidates.json
    (编辑 candidates.json 加 new_value)

    # 2. 批量应用到所有 PDF
    python batch_apply.py --config candidates.json --input-dir pdfs/ --output-dir new_pdfs/

或者:
    python batch_apply.py --config candidates.json \
        --changes '[{"old":"5000","new":"0"}]' \
        --input-dir pdfs/ --output-dir new_pdfs/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import modify_pdf_smart as m


def main():
    parser = argparse.ArgumentParser(description='批量处理多个 PDF')
    parser.add_argument('--config', required=True, help='字段配置 JSON')
    parser.add_argument('--input-dir', required=True, help='输入 PDF 目录')
    parser.add_argument('--output-dir', required=True, help='输出 PDF 目录')
    args = parser.parse_args()

    in_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(in_dir.glob('*.pdf'))
    if not pdfs:
        print(f"目录无 PDF: {in_dir}", file=sys.stderr)
        sys.exit(1)

    with open(args.config, 'r', encoding='utf-8') as f:
        config = json.load(f)
    candidates = config.get('candidates', [])
    new_value_count = sum(1 for c in candidates if c.get('new_value'))
    print(f"配置: {len(candidates)} 候选, {new_value_count} 待修改")

    success = 0
    for pdf_path in pdfs:
        out_path = out_dir / pdf_path.name
        print(f"\n处理: {pdf_path.name}")
        try:
            pages = m.render_pdf(str(pdf_path), scale=config.get('scale', 4))
            for c in candidates:
                if c.get('new_value'):
                    m.apply_field(pages[c['page']], c)
            m.synthesize_pdf(str(pdf_path), pages, str(out_path))
            success += 1
            print(f"  → {out_path}")
        except Exception as e:
            print(f"  失败: {e}", file=sys.stderr)

    print(f"\n完成: {success}/{len(pdfs)} 成功")


if __name__ == '__main__':
    main()