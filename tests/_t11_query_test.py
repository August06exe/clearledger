# -*- coding: utf-8 -*-
"""T11 临时测试脚本：筛选值注入 / 白名单过滤 / 名非法报错（只调引擎，不改引擎）"""
import sys
sys.path.insert(0, '.')
from semantic.query import build_query, run_report, filter_options
from semantic.loader import load_instance

print('=== (a) 注入值 华东\' OR 1=1-- ===')
try:
    sql, params = build_query('sales', 'region_month', {'区域': "华东' OR 1=1--"})
    print('未抛异常 OK')
    print('SQL:', sql)
    print('params:', params)
    print("注入字面量进入 SQL:", ("OR 1=1" in sql) or ("--" in sql))
    rows = run_report('sales', 'region_month', {'区域': "华东' OR 1=1--"})
    regions = sorted({r['区域'] for r in rows})
    print('返回行数:', len(rows), '| 出现的区域:', regions, '（应为全区域 =', ['华北', '华东', '华南', '西北?', '华中', '西南'], '）')
except Exception as e:
    print('抛异常:', type(e).__name__, e)

print()
print('=== (b) 合法值 华东 ===')
sql, params = build_query('sales', 'region_month', {'区域': '华东'})
print('SQL:', sql)
print('params:', params)
print('SQL 含筛选条件:', '"区域" = ?' in sql)
rows = run_report('sales', 'region_month', {'区域': '华东'})
print('返回行数:', len(rows), '| 区域集合:', {r['区域'] for r in rows})

print()
print('=== (c) 名非法 ===')
print('-- c1 报表 key 不存在:')
try:
    run_report('sales', '不存在的报表', {})
    print('!!! 未报错（不符合）')
except Exception as e:
    print('报错:', type(e).__name__, '->', e)
print('-- c2 指标名不存在（loader 交叉校验面）:')
try:
    inst = load_instance('sales')
    inst.metric('不存在的指标')
    print('!!! 未报错（不符合）')
except Exception as e:
    print('报错:', type(e).__name__, '->', e)
print('-- c3 维度名不存在（loader 交叉校验面）:')
try:
    inst = load_instance('sales')
    inst.dimension('不存在的维度')
    print('!!! 未报错（不符合）')
except Exception as e:
    print('报错:', type(e).__name__, '->', e)
print('-- c4 build_query 的 filters 键传不存在的维度名:')
sql, params = build_query('sales', 'region_month', {'不存在的维度': '任意值'})
print('SQL:', sql, '| params:', params, '（键不在白名单 opts 中被忽略——观察：键非法也走静默回退）')
