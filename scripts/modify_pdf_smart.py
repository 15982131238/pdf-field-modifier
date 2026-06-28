#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
modify_pdf_smart.py — 通用 PDF 填空字段修改工具 (主入口)

核心特性:
    - 自动扫描: 识别 PDF 中所有"下划线 + 上方文字"填空区域
    - 自动字号: 扫描原字段值字身高度, 自动计算匹配字号
    - 字体可选: 默认宋体, 可指定微软雅黑/楷体/黑体
    - 保留下划线: 白底范围自动避让下划线
    - 保留矢量: 第 1 页保留原 PDF 矢量, 第 2+ 页嵌入修改图

两种用法:
    # 模式 1: 扫描 + 用户挑选 + 应用
    python modify_pdf_smart.py scan <input.pdf> > candidates.json
    (用户编辑 candidates.json, 给每个候选加 new_value 和 font_choice)
    python modify_pdf_smart.py apply <input.pdf> <output.pdf> --config candidates.json

    # 模式 2: 一键修改 (从原值到新值, 自动定位)
    python modify_pdf_smart.py replace <input.pdf> <output.pdf> \
        --changes '[{"old":"3","new":"6"},{"old":"5000","new":"0"}]'

依赖:
    pip install pypdfium2 pymupdf pillow numpy
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
    import fitz
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"缺少依赖: {e}", file=sys.stderr)
    print("安装: pip install pypdfium2 pymupdf pillow numpy", file=sys.stderr)
    sys.exit(1)


# 默认字体路径
DEFAULT_FONTS = {
    'simsun': 'C:/Windows/Fonts/simsun.ttc',       # 宋体
    'msyh': 'C:/Windows/Fonts/msyh.ttc',          # 微软雅黑
    'simhei': 'C:/Windows/Fonts/simhei.ttf',      # 黑体
    'simkai': 'C:/Windows/Fonts/simkai.ttf',      # 楷体
    'simfang': 'C:/Windows/Fonts/simfang.ttf',    # 仿宋
}


# ============================================================
# 扫描: 找 PDF 中所有"下划线 + 上方文字"区域
# ============================================================

def render_pdf(input_pdf, scale=4):
    """渲染 PDF 每页为 RGB PIL Image"""
    pdf = pdfium.PdfDocument(input_pdf)
    pages = []
    for i in range(len(pdf)):
        img = pdf[i].render(scale=scale).to_pil().convert('RGB')
        pages.append(img)
    pdf.close()
    return pages


def find_horizontal_lines(arr, min_length=80, max_length=900, threshold=80):
    """找下划线: 连续黑色横线 (y 行黑像素 >= 50%)
    过滤: 长度在 [min_length, max_length] 之间 (排除边框/装饰线)
    """
    h, w = arr.shape
    lines = []
    for y in range(h):
        row = arr[y, :]
        black_ratio = (row < threshold).sum() / w
        if black_ratio > 0.15:  # 下划线 + 字段值合计占比, 阈值放宽
            lines.append(y)

    if not lines:
        return []

    # 合并相邻行 (下划线 2-4 像素粗)
    groups = []
    current = [lines[0]]
    for y in lines[1:]:
        if y - current[-1] <= 3:
            current.append(y)
        else:
            groups.append(current)
            current = [y]
    groups.append(current)

    # 过滤: 长度够 + 是横线 (行厚 <= 6) + 长度范围合适
    result = []
    for g in groups:
        if not (2 <= len(g) <= 6):
            continue
        y_top = g[0]
        y_bottom = g[-1]
        mid_y = (y_top + y_bottom) // 2
        # 找这条线 x 范围
        row = arr[mid_y, :] < threshold
        x_runs = []
        in_run = False
        start = 0
        for x in range(len(row)):
            if row[x]:
                if not in_run:
                    start = x
                    in_run = True
            else:
                if in_run:
                    length = x - start
                    if min_length <= length <= max_length:
                        x_runs.append((start, x))
                    in_run = False
        if in_run:
            tail = len(row) - start
            if min_length <= tail <= max_length:
                x_runs.append((start, len(row)))

        for x_left, x_right in x_runs:
            length = x_right - x_left
            if length < min_length or length > max_length:
                continue
            result.append({
                'y': y_top,
                'y_bottom': y_bottom,
                'x_left': x_left,
                'x_right': x_right,
                'length': length
            })
    return result


def find_text_above_underline(arr, line, search_above=60, margin=10, threshold=100):
    """在下划线正上方找最近的字段值 (黑像素区域)
    限制: 只在下方 5-60 像素内找, 不要找上方整行文字
    """
    y_underline = line['y']
    x_left = max(0, line['x_left'] - margin)
    x_right = min(arr.shape[1], line['x_right'] + margin)
    y_search_top = max(0, y_underline - search_above)
    y_search_bottom = max(0, y_underline - 3)  # 留 3 像素间隙

    if y_search_top >= y_search_bottom:
        return None

    band = arr[y_search_top:y_search_bottom, x_left:x_right] < threshold
    rows_with_text = band.any(axis=1)

    if not rows_with_text.any():
        return None

    # 找连续黑字行, 取最靠近下划线的 (y_bottom 最大)
    text_runs = []
    in_run = False
    start = 0
    for y in range(len(rows_with_text)):
        if rows_with_text[y]:
            if not in_run:
                start = y
                in_run = True
        else:
            if in_run:
                text_runs.append((start + y_search_top, y + y_search_top))
                in_run = False
    if in_run:
        text_runs.append((start + y_search_top, len(rows_with_text) + y_search_top))

    if not text_runs:
        return None

    # 取最靠近下划线的一段 (y_bottom 最大)
    text_runs.sort(key=lambda r: r[1], reverse=True)
    y_text_top, y_text_bottom = text_runs[0]

    # 文字 x 范围: 在 [x_left, x_right] 内
    band_text = arr[y_text_top:y_text_bottom, x_left:x_right] < threshold
    cols = band_text.any(axis=0)
    in_run = False
    start = 0
    x_runs = []
    for x in range(len(cols)):
        if cols[x]:
            if not in_run:
                start = x
                in_run = True
        else:
            if in_run:
                x_runs.append((start, x))
                in_run = False
    if in_run:
        x_runs.append((start, len(cols)))

    if not x_runs:
        return None

    # 取覆盖整个文字段的最小 x 范围 (合并所有连续段, 但留 5px 间隔)
    # 处理多字符字段如 "5000", "2026-06-30" (字符间有空白)
    x_runs.sort(key=lambda r: r[0])
    merged = [list(x_runs[0])]
    for s, e in x_runs[1:]:
        if s - merged[-1][1] <= 8:  # 字符间隔 <= 8 像素合并
            merged[-1][1] = e
        else:
            merged.append([s, e])
    text_x_left = min(r[0] for r in merged) + x_left
    text_x_right = max(r[1] for r in merged) + x_left

    # 约束: 字段值宽度 < 下划线宽度 * 0.97 (避免整行作为字段值, 但允许日期类长字段)
    if (text_x_right - text_x_left) > (line['x_right'] - line['x_left']) * 0.97:
        return None

    return {
        'y_top': y_text_top,
        'y_bottom': y_text_bottom,
        'x_left': text_x_left,
        'x_right': text_x_right,
        'height': y_text_bottom - y_text_top,
    }


def measure_text_height(arr, x_left, x_right, y_top, y_bottom, threshold=100):
    """测量黑字字身高度 (连续黑像素行最大长度)"""
    band = arr[y_top:y_bottom, x_left:x_right] < threshold
    rows = band.any(axis=1)
    in_run = False
    start = 0
    max_run = 0
    for y in range(len(rows)):
        if rows[y]:
            if not in_run:
                start = y
                in_run = True
        else:
            if in_run:
                run_len = y - start
                if run_len > max_run:
                    max_run = run_len
                in_run = False
    if in_run:
        run_len = len(rows) - start
        if run_len > max_run:
            max_run = run_len
    return max_run


def detect_font_family(arr, x_left, x_right, y_top, y_bottom, threshold=100):
    """粗略检测字体: 根据笔画粗细判断"""
    band = (arr[y_top:y_bottom, x_left:x_right] < threshold).astype(np.uint8)
    if band.sum() == 0:
        return 'simsun'  # 默认宋体

    # 黑色像素密度
    density = band.sum() / band.size
    # 字符平均宽度 (假设至少 1 个字符)
    width = x_right - x_left
    if width < 10:
        return 'simsun'

    aspect = width / max(1, y_bottom - y_top)

    # 启发式:
    # - 宋体: 密度 ~0.15-0.25, 长宽比 ~0.5-1.0
    # - 微软雅黑: 密度 ~0.25-0.40, 长宽比 ~0.7-1.2 (更粗)
    # - 黑体: 密度 ~0.30-0.45, 长宽比 ~0.6-1.0
    # - 楷体: 密度 ~0.10-0.20, 长宽比 ~0.5-0.9
    if density > 0.30 and aspect > 0.8:
        return 'msyh'
    elif density > 0.28:
        return 'simhei'
    elif density < 0.13:
        return 'simkai'
    else:
        return 'simsun'


def scan_pdf(input_pdf, scale=4):
    """扫描整个 PDF, 返回候选字段清单"""
    pdf = pdfium.PdfDocument(input_pdf)
    candidates = []

    for page_idx in range(len(pdf)):
        img = pdf[page_idx].render(scale=scale).to_pil().convert('L')
        arr = np.array(img)

        # 找下划线
        lines = find_horizontal_lines(arr, min_length=int(60 * scale / 4))

        for line in lines:
            text = find_text_above_underline(arr, line)
            if text is None:
                continue

            # 过滤: 文字段不能覆盖整行 (避免误判整行作为字段)
            if text['x_right'] - text['x_left'] > line['x_right'] - line['x_left'] + 80:
                continue

            # 测量字身高度
            char_height = measure_text_height(
                arr, text['x_left'], text['x_right'],
                text['y_top'], text['y_bottom']
            )

            # 自动字号: 字身高度 / 0.7 (宋体字符字身 ≈ em * 0.7)
            auto_font_size = max(28, min(80, int(char_height / 0.7)))

            # 自动检测字体
            detected_font = detect_font_family(
                arr, text['x_left'], text['x_right'],
                text['y_top'], text['y_bottom']
            )

            candidates.append({
                'id': f'p{page_idx+1}_f{len([c for c in candidates if c["page"] == page_idx])+1}',
                'page': page_idx,
                'underline': {
                    'y': line['y'],
                    'y_bottom': line['y_bottom'],
                    'x_left': line['x_left'],
                    'x_right': line['x_right'],
                },
                'value_above': {
                    'y_top': text['y_top'],
                    'y_bottom': text['y_bottom'],
                    'x_left': text['x_left'],
                    'x_right': text['x_right'],
                },
                'auto_char_height': char_height,
                'auto_font_size': auto_font_size,
                'detected_font': detected_font,
                'new_value': '',          # 用户填
                'font_choice': 'auto',    # auto / simsun / msyh / simhei / simkai
                'font_size': auto_font_size,  # 可被用户覆盖
            })

    pdf.close()
    return candidates


# ============================================================
# 修改: 应用候选字段的 new_value
# ============================================================

def get_font(font_choice, font_path=None):
    """根据选择返回字体路径"""
    if font_path and os.path.exists(font_path):
        return font_path
    if font_choice in DEFAULT_FONTS and os.path.exists(DEFAULT_FONTS[font_choice]):
        return DEFAULT_FONTS[font_choice]
    # 兜底: 找任何可用字体
    for f in ['simsun.ttc', 'msyh.ttc', 'simhei.ttf']:
        path = f'C:/Windows/Fonts/{f}'
        if os.path.exists(path):
            return path
    raise FileNotFoundError("找不到任何系统字体")


def apply_field(img, candidate):
    """应用一个字段修改: 白底覆盖 + 写新字"""
    val = candidate['value_above']
    line = candidate['underline']

    y_top = val['y_top']
    y_bottom = val['y_bottom']
    y_underline = line['y']
    x_left = val['x_left']
    x_right = val['x_right']
    new_value = candidate['new_value']

    if not new_value:
        return False

    # 字体
    if candidate.get('font_choice') == 'auto':
        font_path = get_font(candidate.get('detected_font', 'simsun'))
    else:
        font_path = get_font(candidate.get('font_choice', 'simsun'))

    font_size = candidate.get('font_size', candidate.get('auto_font_size', 40))
    font = ImageFont.truetype(font_path, font_size)

    draw = ImageDraw.Draw(img)

    # 白底覆盖 (避让下划线)
    draw.rectangle(
        [x_left - 3, y_top - 3, x_right + 3, y_underline - 2],
        fill='white'
    )

    # 写新字 (中底对齐)
    x_center = (x_left + x_right) // 2
    draw.text(
        (x_center, y_bottom),
        new_value,
        font=font,
        fill='black',
        anchor='ms'
    )
    return True


def synthesize_pdf(input_pdf, page_images, output_pdf):
    """合成最终 PDF: 第 1 页矢量保留, 第 2+ 页嵌入图"""
    doc = fitz.open(input_pdf)
    new_doc = fitz.open()

    # 第 1 页: 保留矢量
    if len(doc) > 0:
        new_doc.insert_pdf(doc, from_page=0, to_page=0)

    # 第 2~N 页: 嵌入修改图
    for i in range(1, len(page_images)):
        page = new_doc.new_page(width=595.32, height=841.92)
        rect = fitz.Rect(0, 0, 595.32, 841.92)
        buf = io.BytesIO()
        page_images[i].save(buf, format='PNG', optimize=False)
        page.insert_image(rect, stream=buf.getvalue())

    new_doc.save(
        output_pdf,
        garbage=4,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        clean=True
    )
    new_doc.close()
    doc.close()


# ============================================================
# 替换模式: 自动定位原值 → 替换为新值
# ============================================================

def find_field_by_old_value(candidates, old_value):
    """从候选清单中找最像 old_value 的字段 (基于字符数估算)"""
    if not old_value:
        return None

    expected_chars = len(old_value)
    if expected_chars == 0:
        return None

    # 判断 old_value 是中文还是数字/英文
    is_chinese = any('\u4e00' <= ch <= '\u9fff' for ch in old_value)

    scored = []
    for c in candidates:
        val = c['value_above']
        width = val['x_right'] - val['x_left']
        height = val['y_bottom'] - val['y_top']

        if height == 0 or width == 0:
            continue

        # 过滤: 字段值高度 < 12 像素的(噪点/横线误识)跳过
        if height < 12:
            continue

        # 过滤: 下划线太短(<30)或太长(>1200)跳过
        underline_w = c['underline']['x_right'] - c['underline']['x_left']
        if underline_w < 30 or underline_w > 1200:
            continue

        # 估算字符数
        # scale=4 下数字字符: 高度 25-30px, 单字宽度 ≈ 高度的 0.85 倍
        # 中文字符: 高度 35-40px, 单字宽度 ≈ 高度的 1.5 倍
        # 关键: 根据字段值字身高度过滤掉不相符的字形
        diff = 999  # 默认大差值 (会被过滤)
        if is_chinese:
            # 中文 old_value: 跳过 height<30 的数字字段
            if height >= 30:
                char_width_est = max(30, height * 1.5)
                est_chars = max(1, round(width / char_width_est))
                diff = abs(est_chars - expected_chars)
                if est_chars == expected_chars:
                    diff = max(0, diff - 1)
        else:
            # 数字 old_value: 跳过 height>35 的中文字段
            if height <= 35:
                char_width_est = max(20, height * 0.85)
                est_chars = max(1, round(width / char_width_est))
                diff = abs(est_chars - expected_chars)
                if est_chars == expected_chars:
                    diff = max(0, diff - 1)

        # 加权: 已占用字段加重 (让未占用的字段优先匹配)
        if c.get('new_value'):
            diff += 999

        scored.append((diff, c))

    scored.sort(key=lambda x: x[0])
    return scored[0][1] if scored else None


def replace_mode(input_pdf, output_pdf, changes):
    """一键替换模式: 从 (old, new) 列表自动定位并修改"""
    # 扫描候选
    candidates = scan_pdf(input_pdf)

    # 对每个 (old, new) 找匹配候选并应用
    pages = render_pdf(input_pdf)
    applied = []
    for change in changes:
        old = change['old']
        new = change['new']
        field = find_field_by_old_value(candidates, old)
        if field is None:
            print(f"未找到 '{old}' 对应字段", file=sys.stderr)
            continue
        if field['new_value']:
            print(f"字段 '{old}' 已被占用, 跳过", file=sys.stderr)
            continue

        field['new_value'] = new
        apply_field(pages[field['page']], field)
        applied.append(field['id'])
        print(f"  ✓ '{old}' → '{new}' ({field['id']})", file=sys.stderr)

    # 合成 PDF
    synthesize_pdf(input_pdf, pages, output_pdf)
    print(f"  应用 {len(applied)}/{len(changes)} 个修改", file=sys.stderr)
    print(f"  输出: {output_pdf}", file=sys.stderr)


# ============================================================
# CLI 入口
# ============================================================

def cmd_scan(args):
    """scan 子命令: 扫描候选字段"""
    print(f"扫描: {args.input_pdf}", file=sys.stderr)
    candidates = scan_pdf(args.input_pdf)
    print(f"找到 {len(candidates)} 个候选字段", file=sys.stderr)

    output = {
        'input_pdf': args.input_pdf,
        'scale': args.scale,
        'candidates': candidates
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_apply(args):
    """apply 子命令: 应用修改"""
    if not os.path.exists(args.config):
        print(f"配置文件不存在: {args.config}", file=sys.stderr)
        sys.exit(1)

    with open(args.config, 'r', encoding='utf-8') as f:
        config = json.load(f)

    candidates = config.get('candidates', [])
    new_value_count = sum(1 for c in candidates if c.get('new_value'))
    print(f"输入: {args.input_pdf}", file=sys.stderr)
    print(f"输出: {args.output_pdf}", file=sys.stderr)
    print(f"待修改字段: {new_value_count}/{len(candidates)}", file=sys.stderr)

    pages = render_pdf(args.input_pdf, scale=config.get('scale', 4))
    applied = 0
    for c in candidates:
        if not c.get('new_value'):
            continue
        print(f"  {c['id']}: '{c['new_value']}' "
              f"@ ({c['value_above']['x_left']},{c['value_above']['y_top']}) "
              f"字号={c.get('font_size', c.get('auto_font_size', 40))} "
              f"字体={c.get('font_choice', 'auto')}", file=sys.stderr)
        if apply_field(pages[c['page']], c):
            applied += 1

    synthesize_pdf(args.input_pdf, pages, args.output_pdf)
    size = os.path.getsize(args.output_pdf)
    print(f"完成: {applied} 个字段已修改, {args.output_pdf} ({size/1024/1024:.2f} MB)", file=sys.stderr)


def cmd_replace(args):
    """replace 子命令: 一键替换"""
    if not os.path.exists(args.input_pdf):
        print(f"PDF 不存在: {args.input_pdf}", file=sys.stderr)
        sys.exit(1)

    try:
        changes = json.loads(args.changes)
    except json.JSONDecodeError as e:
        print(f"changes JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    replace_mode(args.input_pdf, args.output_pdf, changes)


def main():
    parser = argparse.ArgumentParser(
        description='通用 PDF 填空字段修改工具 (自动定位/自动字号)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
用法示例:

  # 1. 扫描候选字段
  python modify_pdf_smart.py scan input.pdf > candidates.json

  # 编辑 candidates.json, 给每个候选加:
  #   "new_value": "新值",
  #   "font_choice": "simsun",  # 或 auto / msyh / simhei / simkai
  #   "font_size": 40           # 可选, 默认用 auto_font_size

  # 2. 应用修改
  python modify_pdf_smart.py apply input.pdf output.pdf --config candidates.json

  # 3. 一键替换 (从原值到新值)
  python modify_pdf_smart.py replace input.pdf output.pdf \\
      --changes '[{"old":"3","new":"6"},{"old":"5000","new":"0"}]'
        '''
    )
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # scan
    p_scan = subparsers.add_parser('scan', help='扫描 PDF 中所有候选字段')
    p_scan.add_argument('input_pdf', help='输入 PDF 路径')
    p_scan.add_argument('--scale', type=int, default=4, help='渲染缩放 (默认 4)')

    # apply
    p_apply = subparsers.add_parser('apply', help='应用修改 (基于 candidates.json)')
    p_apply.add_argument('input_pdf', help='输入 PDF 路径')
    p_apply.add_argument('output_pdf', help='输出 PDF 路径')
    p_apply.add_argument('--config', required=True, help='字段配置 JSON')

    # replace
    p_replace = subparsers.add_parser('replace', help='一键替换 (自动定位原值)')
    p_replace.add_argument('input_pdf', help='输入 PDF 路径')
    p_replace.add_argument('output_pdf', help='输出 PDF 路径')
    p_replace.add_argument('--changes', required=True,
                           help='JSON: [{"old":"3","new":"6"}]')

    args = parser.parse_args()

    if args.command == 'scan':
        cmd_scan(args)
    elif args.command == 'apply':
        cmd_apply(args)
    elif args.command == 'replace':
        cmd_replace(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()