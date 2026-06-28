# 字段检测与坐标测量

本 skill 提供两种字段定位方式：**自动扫描**（推荐）和**手动指定坐标**。

## 方式 1: 自动扫描 (推荐)

```bash
python scripts/modify_pdf_smart.py scan input.pdf > candidates.json
```

脚本自动检测所有"下划线+上方文字"作为候选字段。输出 JSON：

```json
{
  "id": "p2_f3",
  "page": 1,
  "value_above": {"y_top": 239, "y_bottom": 267, "x_left": 1602, "x_right": 1715},
  "underline": {"y": 281, "y_bottom": 283, "x_left": 1599, "x_right": 1808},
  "auto_char_height": 28,
  "auto_font_size": 40,
  "detected_font": "simsun",
  "new_value": ""
}
```

**字段含义**：
- `id` — 唯一标识 (page_field)
- `value_above` — 字段值 bounding box（白底覆盖范围 + 写新字位置）
- `underline` — 下划线位置（白底绝不能覆盖到这里）
- `auto_char_height` — 自动测量的字身高度（scale=4 像素）
- `auto_font_size` — 自动计算的字号
- `detected_font` — 自动检测的字体

用户编辑 JSON，给要改的候选加 `new_value`、`font_choice`、`font_size`。

## 方式 2: 手动指定坐标

适用场景：scan 没找到、自动定位不准、需要像素级控制。

### 步骤

1. **渲染 PDF 为 PNG**

```bash
python scripts/render_preview.py input.pdf preview/
```

输出 `preview/page_<N>.png` (scale=4，A4: 2382x3368)。

2. **量字段坐标**

用 PowerShell 量坐标：

```powershell
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bm = [System.Drawing.Bitmap]::FromFile("preview\page_2.png")
function px($x, $y) { "x=$x y=$y" }
px 940 260
# 输出: x=940 y=260
$bm.Dispose()
```

或用画图：打开 PNG，鼠标悬停，状态栏显示 (x, y)。

3. **配置 candidates.json**

```json
{
  "input_pdf": "input.pdf",
  "candidates": [
    {
      "page": 1,
      "value_above": {"y_top": 240, "y_bottom": 280, "x_left": 935, "x_right": 960},
      "underline": {"y": 282, "y_bottom": 283, "x_left": 937, "x_right": 1146},
      "new_value": "6",
      "font_size": 40,
      "font_choice": "simsun"
    }
  ]
}
```

## 关键约束

### 白底范围不能覆盖下划线

```python
# 修改脚本中的白底范围
white_box = (
    x_left - 3,         # 左扩 3 像素
    y_top - 3,          # 字顶之上 3 像素
    x_right + 3,        # 右扩 3 像素
    y_underline - 2     # 下划线之上 2 像素 (关键!)
)
```

如果 `y_underline` 估错，下划线会被擦。

### 字号匹配

| scale=4 字身高度 | 推荐字号 | PDF 字号 |
| --- | --- | --- |
| 24-30 像素 | 36-40 | 6-7pt |
| 30-36 像素 | 44-48 | 7-9pt |
| 36-44 像素 | 52-60 | 9-11pt |
| 44-60 像素 | 64-80 | 11-15pt |

字号 ≈ 字身高度 / 0.7（宋体字符字身 ≈ em * 0.7）。

### 字底对齐

写新字时用 `anchor='ms'`（中底对齐），让字底贴在原字段字字底线：

```python
draw.text(
    (x_center, y_bottom),  # baseline = 原字段字字底 y
    new_value,
    font=font,
    fill='black',
    anchor='ms'  # 中底对齐
)
```

## 常见 PDF 字段布局

| PDF 类型 | 字段示例 | 字号 |
| --- | --- | --- |
| 就业协议书 | 试用期、薪资、报到期限 | 28px 字身 / 40 字号 |
| 合同 | 金额、单价、日期 | 28px 字身 / 40 字号 |
| 申请表 | 姓名、电话、身份证 | 28px 字身 / 40 字号 |
| 成绩单 | 分数、排名 | 32px 字身 / 44 字号 |
| 通知单 | 标题、金额 | 36px 字身 / 48 字号 |

## 反复踩的坑

1. **下划线被擦**：白底范围 > y_underline。留 2 像素 buffer。
2. **字号太大/太小**：用 auto_font_size，不要凭感觉选字号。
3. **新字飘在中线**：用了 `'mm'` 居中，没用 `'ms'` 中底。
4. **多字符字段识别为单字符**：find_text_above_underline 没合并字符段。
5. **PDF 边框横线被误识别**：min_length 太低，提高到 80。
6. **整行横线被误识别**：max_length 设为 900，过滤装饰线。
7. **扫描出 0 候选**：检查 PDF 是否有下划线（不是表格线、不是虚线）。
8. **扫描出太多候选 (>50)**：调大 min_length 到 150。

## 多页 PDF

- 第 1 页通常是矢量模板（边框、标题），不应改
- 第 2+ 页通常是填写页（用户填写的内容）
- 修改第 1 页 → 矢量被破坏，改后整页变图片
- 推荐：只改第 2+ 页

脚本默认保留第 1 页矢量，其他页嵌入修改图。
如果你的"填空页"在第 1 页，参见 `references/font-sizing.md` 的"特殊场景"。