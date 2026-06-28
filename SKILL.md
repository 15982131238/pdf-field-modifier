---
name: pdf-field-modifier
description: |
  通用 PDF 填空字段修改工具: 修改 PDF 中已有字段值（数字、日期、文字）。
  适用于任何有"下划线+上方文字"模式的 PDF: 就业协议书、劳动合同、申请表、
  合同、成绩单、通知单等。
  Use when the user says: "改 PDF 字段"、"修改 PDF 数字"、"改 PDF 日期"、
  "改 PDF 文字"、"PDF 填空"、"改合同金额"、"改合同日期"。
  Do NOT use for: DOCX/PPT 修改、PDF 重排版、新建 PDF、AcroForm 表单
  (用 pypdf)、PDF 内容提取/OCR (本 skill 不带 OCR)。
---

# PDF Field Modifier — 通用 PDF 填空字段修改

## 这个 skill 做什么

修改任何有"下划线+上方文字"模式的 PDF 字段值。**全自动定位 + 自动字号匹配 + 字体可选**。

**核心原理**：
1. 渲染 PDF (scale=4)
2. 自动扫描所有"下划线"（连续黑色横线）
3. 在下划线正上方找最近的字段值文字段（黑像素）
4. 自动测量字段值字身高度 → 计算匹配字号
5. 自动检测字体（宋体/微软雅黑/黑体/楷体）
6. 用户从候选里挑要改的 → 脚本擦除 + 写新字
7. 合成最终 PDF（保留矢量 + PNG 嵌入）

## 三种使用模式

### 模式 1: scan + apply（最通用，适合批量修改）

```bash
# 1. 扫描所有候选字段
python scripts/modify_pdf_smart.py scan input.pdf > candidates.json

# 2. 编辑 candidates.json: 给要改的候选加 new_value
#    {
#      "id": "p2_f3",
#      "new_value": "0",
#      "font_choice": "simsun",  # simsun / msyh / simhei / simkai / auto
#      "font_size": 40           # 可选, 默认 auto_font_size
#    }

# 3. 应用修改生成新 PDF
python scripts/modify_pdf_smart.py apply input.pdf output.pdf --config candidates.json
```

### 模式 2: replace（一键替换，适合改少量字段）

```bash
python scripts/modify_pdf_smart.py replace input.pdf output.pdf \
    --changes '[{"old":"3","new":"6"},{"old":"5000","new":"0"}]'
```

**适用场景**：
- 用户明确知道原值是什么
- 字段值在 PDF 中是文本（数字/英文）
- 适合改日期、金额、数量等

**算法**：扫描候选 → 按字符数估算 + 中/英自适应匹配 → 自动定位

### 模式 3: 手动坐标（特殊场景）

直接传 JSON 坐标（详见 `references/field-detection.md`）。

## 核心算法：自动字段定位

每个候选字段包含：

| 字段 | 含义 |
| --- | --- |
| `id` | 唯一标识 `p<page>_f<N>` |
| `page` | 页码 0-indexed |
| `value_above` | 字段值 bounding box (x_left, y_top, x_right, y_bottom) |
| `underline` | 下划线位置 (x_left, y, x_right) |
| `auto_char_height` | 自动测量的字身高度 (scale=4 像素) |
| `auto_font_size` | 自动计算的字号 (≈ 字身 / 0.7) |
| `detected_font` | 自动检测的字体 (simsun/msyh/simhei/simkai) |

**扫描算法**：
1. 对每页灰度图扫描所有黑行（每像素 < 100 算黑）
2. 合并相邻黑行 → 检测"下划线段"（行厚 2-6 px，长度 50-900 px）
3. 排除整行边框（长度 > 1200 px）和噪点（长度 < 30 px）
4. 对每条下划线，在其正上方 3-60 像素范围找最近文字段
5. 字段值宽度 < 下划线宽度 * 0.97（避免误识整行）
6. 测量字段值字身高度 → 字号 = 字身 / 0.7（宋体字符字身 ≈ em * 0.7）
7. 测量字符笔画密度 → 推断字体

**自动字体检测**：
- 黑色像素密度 + 字符长宽比 → 宋体/微软雅黑/黑体/楷体
- 默认宋体 (simsun)，失败 fallback 到微软雅黑

## 输出 contract

- 文件 `<output>.pdf`
- 页面数与原 PDF 相同
- 第 1 页：原矢量保留
- 第 2~N 页：嵌入修改后的 PNG（无损，文字清晰不可复制）
- 文件大小：通常 1-3 MB

## Failure handling

- **PDF 加密** → 报错要求密码
- **扫描出 0 个候选** → 调小 min_length (默认 80 → 50) 重新扫描
- **扫描出太多候选 (>50)** → 调大 min_length (默认 80 → 150) 减少噪点
- **replace 模式找错字段** → 用 scan 模式手动确认字段位置
- **字号不匹配** → 在 candidates.json 中手动指定 font_size
- **字体不对** → 在 candidates.json 中指定 font_choice (simsun/msyh/simhei/simkai)
- **下划线被擦** → 检查 white_box 下边界是否 < y_underline - 2
- **PDF 无文本层** → 本 skill 就是为此设计的，能正常工作
- **OCR 不可用** → 本 skill 不依赖 OCR，靠下划线扫描定位

## Windows (win32) platform notes

- Python 直接调用：`python scripts/modify_pdf_smart.py ...`
- 字体路径：`C:\\Windows\\Fonts\\simsun.ttc`（双反斜杠）
- 中文路径没问题（Python 3 UTF-8）
- 安装依赖：`pip install pypdfium2 pymupdf pillow numpy`

## Examples

### Example 1: 改就业协议书 4 个字段 (replace 模式)

```bash
python scripts/modify_pdf_smart.py replace 就业协议书.pdf 修改后.pdf \
    --changes '[{"old":"3","new":"6"},{"old":"5000","new":"0"},
                {"old":"7000","new":"0"},{"old":"2026-06-30","new":"2026-07-02"}]'
```

输出：4 个字段全改对，下划线保住，字号匹配。

### Example 2: 改合同日期 + 金额 (scan + apply)

```bash
# 扫描
python scripts/modify_pdf_smart.py scan 合同.pdf > fields.json

# 编辑 fields.json: 给要改的字段加 new_value
# fields.json 中找 id="p2_f3", 改为:
#   "new_value": "50000"
#   "font_choice": "msyh"

# 应用
python scripts/modify_pdf_smart.py apply 合同.pdf 新合同.pdf --config fields.json
```

### Example 3: 批量改多份相同模板 (replace 模式)

```bash
for f in 申请表_*.pdf; do
    python scripts/modify_pdf_smart.py replace "$f" "new_$f" \
        --changes '[{"old":"2026-06-30","new":"2026-07-15"}]'
done
```

详细字段坐标测量算法见 `references/field-detection.md`。
字号匹配算法细节见 `references/font-sizing.md`。