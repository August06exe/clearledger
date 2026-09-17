# -*- coding: utf-8 -*-
"""Excel 导出（xlsxwriter 内存生成）"""
from __future__ import annotations

import io

import xlsxwriter


def to_xlsx(columns: list[tuple[str, str]], rows: list[dict], sheet: str = "报表", note: str | None = None) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet(sheet[:31])

    hdr = wb.add_format({"bold": True, "bg_color": "#1D4ED8", "font_color": "white", "border": 1})
    money = wb.add_format({"num_format": "#,##0.00"})
    int_fmt = wb.add_format({"num_format": "#,##0"})
    pct = wb.add_format({"num_format": "0.00%"})

    start = 0
    if note:  # 数据过期等警示（红灯时导出旧数据必须告知）
        warn_fmt = wb.add_format({"bold": True, "bg_color": "#FEF2F2", "font_color": "#B91C1C"})
        ws.merge_range(0, 0, 0, max(len(columns) - 1, 1), "⚠ " + note, warn_fmt)
        start = 1

    for j, (_, label) in enumerate(columns):
        ws.write(start, j, label, hdr)

    pct_keys = {"毛利率", "净利率", "收入环比", "毛利环比"}
    for i, row in enumerate(rows, start=start + 1):
        for j, (key, label) in enumerate(columns):
            v = row.get(key)
            if isinstance(v, bool):
                ws.write(i, j, int(v))
            elif isinstance(v, int):
                ws.write_number(i, j, v, int_fmt)
            elif isinstance(v, float):
                if label in pct_keys:
                    ws.write_number(i, j, v, pct)
                else:
                    ws.write_number(i, j, v, money)
            else:
                ws.write(i, j, "" if v is None else str(v))

    ws.freeze_panes(start + 1, 0)
    ws.autofit()
    wb.close()
    return buf.getvalue()
