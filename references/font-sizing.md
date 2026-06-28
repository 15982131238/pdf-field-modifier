# 字号匹配算法

让新字看起来跟原字同字号、同位置，是 PDF 字段修改的核心技术点。

## scale=4 渲染的尺寸基准

- A4 PDF 原始尺寸：595.32 x 841.92 pt
- scale=4 渲染：2382 x 3368 像素
- **1 pt = 4 像素 @ scale=4**

## 自动字号测量算法

```python
def measure_text_height(arr, x_left, x_right, y_top, y_bottom, threshold=100):
    """测量黑字字身高度 (连续黑像素行最大长度)"""
    band = arr[y_top:y_bottom, x_left:x_right] < threshold
    rows = band.any(axis=1)
    
    # 找最长连续黑字行段
    max_run = 0
    in_run = False
    start = 0
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
```

**字号换算**：

| 字符类型 | em (字号) | 字身高度 |
| --- | --- | --- |
| 宋体字符 | em | em * 0.7 |
| 数字 | em | em * 0.95 (数字比中文占满字身) |

**公式**：
- 中文字符：字号 = 字身高度 / 0.7
- 数字字符：字号 = 字身高度 / 0.95

## 实测典型字段字号

| PDF 类型 | scale=4 字身高度 | 推荐 PIL 字号 |
| --- | --- | --- |
| 标准填空 | 28 像素 | 40 (数字) / 44 (中文) |
| 略大填空 | 36 像素 | 48 |
| 表格填空 | 32 像素 | 44 |
| 重要金额 | 40 像素 | 56 |
| 标题 | 60+ 像素 | 80+ |

## 中底对齐 `anchor='ms'`

PIL 的 `draw.text` 默认 y 坐标是字符 baseline。`anchor` 参数：

- `'lt'`：左上
- `'mm'`：中心
- `'ms'`：**中底**（baseline 在 y，水平居中在 x）
- `'ls'`：左下（baseline 在 y，水平左对齐在 x）

**为什么用 `anchor='ms'`？**

PDF 字段字是 baseline 对齐的。要让新字字底贴在原字段字字底线上：

1. 量出原字段字字底 y（黑字行最低像素 y）
2. `draw.text((x_center, y_bottom), text, font=font, fill='black', anchor='ms')`
3. PIL 自动把 baseline 对齐到 y_bottom，新字看起来跟原字同位置同高度

**如果用 `'mm'` 居中**：新字中心对齐到原字段字中心，但字底会高于原字底线——新字"飘"在中线上。

## 白底范围设计

```python
draw.rectangle(
    [x_left - 5, y_top - 5, x_right + 5, y_underline - 2],
    fill='white'
)
```

- 左右各扩 5 像素：防止擦不干净
- y_top - 5：擦到字顶上方一点
- **y_underline - 2**：留 2 像素 buffer 保留下划线（**关键！**）

## 字体自动检测

```python
def detect_font_family(arr, x_left, x_right, y_top, y_bottom, threshold=100):
    band = (arr[y_top:y_bottom, x_left:x_right] < threshold).astype(np.uint8)
    density = band.sum() / band.size  # 黑色像素密度
    width = x_right - x_left
    height = y_bottom - y_top
    aspect = width / max(1, height)

    # 启发式判断:
    # - 宋体: 密度 0.15-0.25, 长宽比 0.5-1.0
    # - 微软雅黑: 密度 0.25-0.40, 长宽比 0.7-1.2
    # - 黑体: 密度 0.30-0.45, 长宽比 0.6-1.0
    # - 楷体: 密度 0.10-0.20, 长宽比 0.5-0.9
    if density > 0.30 and aspect > 0.8:
        return 'msyh'  # 微软雅黑
    elif density > 0.28:
        return 'simhei'  # 黑体
    elif density < 0.13:
        return 'simkai'  # 楷体
    else:
        return 'simsun'  # 宋体 (默认)
```

## 字体选择

| 字体 | 路径 | 特点 |
| --- | --- | --- |
| 宋体 (SimSun) | `C:\Windows\Fonts\simsun.ttc` | **首选**，最常见 PDF 中文字体 |
| 微软雅黑 | `C:\Windows\Fonts\msyh.ttc` | 现代 PDF 常用，字略粗 |
| 黑体 (SimHei) | `C:\Windows\Fonts\simhei.ttf` | 粗体，标题用 |
| 楷体 (SimKai) | `C:\Windows\Fonts\simkai.ttf` | 手写风格 |

**默认宋体**——多数 PDF 都用宋体。如果改完后跟原字风格不一致，手动指定 font_choice。

## 字号常见坑

1. **用 56 字号**：字身比原字大 50%，新字"溢出"字段范围。
2. **用 32 字号**：字身比原字小 20%，新字显得"小一号"。
3. **用 `'mm'` 居中**：新字浮在中线上。
4. **不写 `anchor='ms'`**：默认是 `la`，baseline 跟 y 坐标不一致。

**稳健默认**：40 字号 + `anchor='ms'` + simsun.ttc + 字底 y = 原字段字字底 y。

## 字号自适应（实验性）

如果你**不知道原字号**，可以用自适应算法：

```python
def find_best_font_size(text, font_path, target_height, x_center, y_bottom):
    """搜索让字身最接近 target_height 的字号"""
    best_size = 40
    best_diff = float('inf')
    for size in range(28, 80):
        font = ImageFont.truetype(font_path, size)
        # 画字到临时图, 测量字身高度
        tmp = Image.new('L', (200, 200), 255)
        d = ImageDraw.Draw(tmp)
        d.text((100, 100), text, font=font, fill=0, anchor='mm')
        # 测量字身
        arr = np.array(tmp)
        cols = (arr < 100).any(axis=0)
        if not cols.any():
            continue
        rows = (arr < 100).any(axis=1)
        max_run = 0
        in_run = False
        start = 0
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
        diff = abs(max_run - target_height)
        if diff < best_diff:
            best_diff = diff
            best_size = size
    return best_size
```

但本 skill 默认不调用（性能开销大），用 auto_font_size 已经够用。