"""生成一张模拟化验单图片，用来验证「照片 → 数值 → 对照」这条链路。"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = Path(__file__).resolve().parent / "demo" / "化验单.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

W, H = 900, 620
img = Image.new("RGB", (W, H), "white")
draw = ImageDraw.Draw(img)


# 中文字体优先用 Windows 自带；换到别的系统会自动回退，
# 只是中文可能显示成方框——这个脚本只用于生成演示图，不影响主流程。
FONT_CANDIDATES = {
    False: [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"],
    True: [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"],
}


def load_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES[bold]:
        if pathlib.Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def font(size: int, bold: bool = False):
    return load_font(size, bold=bold)


draw.text((250, 24), "某某市第一医院  检验报告单", font=font(26, True), fill="black")
draw.text((40, 74), "姓名：李某某", font=font(18), fill="black")
draw.text((240, 74), "性别：男", font=font(18), fill="black")
draw.text((380, 74), "年龄：43", font=font(18), fill="black")
draw.text((560, 74), "科室：心内科", font=font(18), fill="black")
draw.text((40, 104), "样本：静脉血（空腹 12 小时）", font=font(16), fill="#444444")
draw.text((560, 104), "报告日期：2026-11-20", font=font(16), fill="#444444")

rows = [
    ("项目", "结果", "单位", "参考范围"),
    ("总胆固醇 TC", "6.42", "mmol/L", "3.10 – 5.20"),
    ("甘油三酯 TG", "2.85", "mmol/L", "0.40 – 1.70"),
    ("低密度脂蛋白 LDL-C", "4.31", "mmol/L", "< 3.40"),
    ("高密度脂蛋白 HDL-C", "0.86", "mmol/L", "> 1.00"),
    ("空腹血糖 FPG", "6.35", "mmol/L", "3.90 – 6.10"),
    ("血尿酸 UA", "486", "μmol/L", "208 – 428"),
    ("收缩压 SBP", "142", "mmHg", "90 – 139"),
]
top, row_h = 150, 46
col_x = [50, 360, 500, 640]
for index, row in enumerate(rows):
    y = top + index * row_h
    if index == 0:
        draw.rectangle([40, y - 6, W - 40, y + row_h - 10], fill="#EEF3FA")
    weight = font(17, True) if index == 0 else font(17)
    for col, text in enumerate(row):
        draw.text((col_x[col], y), text, font=weight, fill="black")
    draw.line([(40, y + row_h - 10), (W - 40, y + row_h - 10)], fill="#CCCCCC", width=1)

# 把高于参考值的项标红加粗（模拟医院系统的箭头提示）
draw.text((820, top + 1 * row_h), "↑", font=font(20, True), fill="#C00000")
draw.text((820, top + 2 * row_h), "↑", font=font(20, True), fill="#C00000")
draw.text((820, top + 3 * row_h), "↑", font=font(20, True), fill="#C00000")
draw.text((820, top + 4 * row_h), "↓", font=font(20, True), fill="#0070C0")
draw.text((820, top + 5 * row_h), "↑", font=font(20, True), fill="#C00000")
draw.text((820, top + 6 * row_h), "↑", font=font(20, True), fill="#C00000")
draw.text((820, top + 7 * row_h), "↑", font=font(20, True), fill="#C00000")

draw.text((40, H - 60), "检验者：王某      审核者：张某      本报告仅对本次样本负责", font=font(14), fill="#666666")

img.save(OUT)
print(f"written: {OUT} ({W}x{H})")
