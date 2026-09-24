# -*- coding: utf-8 -*-
"""语义引擎（通用，零业务预设）：五配置加载与交叉校验"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INSTANCES_DIR = ROOT / "instances"
TEST_FIXTURES_DIR = ROOT / "tests" / "fixtures" / "instances"

CONFIG_FILES = {
    "sources": "sources.yml",
    "wide": "wide.yml",
    "dimensions": "dimensions.yml",
    "metrics": "metrics.yml",
    "dashboard": "dashboard.yml",
}


class ConfigError(Exception):
    """配置不合法——AI 装配的第一道机器防线"""


@dataclass
class Instance:
    name: str
    title: str
    inbox: Path
    db_path: Path           # 相对生成 pipeline/ 的 dbt path
    pipeline_dir: Path
    sources: dict = field(default_factory=dict)
    wide: dict = field(default_factory=dict)
    dimensions: list = field(default_factory=list)
    metrics: list = field(default_factory=list)
    dashboard: dict = field(default_factory=dict)

    # ---- 便捷访问 ----
    def source(self, name: str) -> dict:
        for s in self.sources.get("sources", []):
            if s["name"] == name:
                return s
        raise ConfigError(f"实例 [{self.name}] 未声明数据源: {name}")

    def fields_of(self, source_name: str) -> list[dict]:
        return self.source(source_name).get("fields", [])

    def columns_of(self, source_name: str) -> set[str]:
        """某源的全部英文列（map 后）"""
        return {f["map"] for f in self.fields_of(source_name)}

    def dimension(self, name: str) -> dict:
        for d in self.dimensions:
            if d["name"] == name:
                return d
        raise ConfigError(f"实例 [{self.name}] 未声明维度: {name}")

    def metric(self, name: str) -> dict:
        for m in self.metrics:
            if m["name"] == name:
                return m
        raise ConfigError(f"实例 [{self.name}] 未声明指标: {name}")


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"缺少配置文件: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件格式错误（应为映射）: {path}")
    return data


def load_instance(name: str) -> Instance:
    """加载实例五配置并做交叉引用校验。任何引用悬空立即报错——fail fast。

    双根发现：正式账套在 instances/，测试夹具账套在 tests/fixtures/instances/
    （下划线前缀约定对两处一致——夹具永不进正式账套清单）。
    """
    for d in (INSTANCES_DIR / name, TEST_FIXTURES_DIR / name):
        if d.exists():
            return load_instance_dir(d, name)
    raise ConfigError(f"实例不存在: {name}")


def load_instance_dir(d: Path, name: str) -> Instance:
    """从任意目录加载实例配置（load_instance 的目录变体）。

    配置工作台的草稿校验靠它：把六份配置（含草稿）放进临时目录即可走全套交叉校验，
    不必真的落盘到 instances/。语义与 load_instance 完全一致。
    """
    if not d.exists():
        raise ConfigError(f"实例目录不存在: {d}")

    meta = _read_yaml(d / "instance.yml")
    inst = Instance(
        name=name,
        title=meta.get("title", name),
        inbox=(d / meta.get("inbox", "data/inbox")).resolve(),
        db_path=Path(meta.get("database", f"../../data/warehouse/{name}.duckdb")),
        pipeline_dir=d / "pipeline",
        sources=_read_yaml(d / CONFIG_FILES["sources"]),
        wide=_read_yaml(d / CONFIG_FILES["wide"]),
        dimensions=_read_yaml(d / CONFIG_FILES["dimensions"]).get("dimensions", []),
        metrics=_read_yaml(d / CONFIG_FILES["metrics"]).get("metrics", []),
        dashboard=_read_yaml(d / CONFIG_FILES["dashboard"]),
    )

    # ---- 结构完整性：缺键要 ConfigError 指名道姓，不能裸 KeyError（N-09）----
    for s in inst.sources.get("sources", []):
        for i, f in enumerate(s.get("fields", [])):
            for k in ("cn", "map"):
                if k not in f:
                    raise ConfigError(f"[{name}] sources.{s.get('name')}.fields[{i}] 缺少必需键 {k}")
    for rep in inst.dashboard.get("reports", []):
        for k in ("key", "dimension", "metrics"):
            if k not in rep:
                raise ConfigError(f"[{name}] dashboard.reports[{rep.get('key', '?')}] 缺少必需键 {k}")

    # ---- 交叉引用校验 ----
    wide = inst.wide.get("wide", {})
    main = wide.get("main")
    if not main:
        raise ConfigError(f"[{name}] wide.yml 缺少 main")
    if not wide.get("name"):
        raise ConfigError(f"[{name}] wide.yml 缺少 name")
    inst.source(main)  # 存在性

    wide_cols: set[str] = set(inst.columns_of(main))
    for j in wide.get("joins", []):
        for k in ("table", "keys"):
            if k not in j:
                raise ConfigError(f"[{name}] wide.joins[{j.get('table', '?')}] 缺少必需键 {k}")
        tbl = j["table"]
        inst.source(tbl)
        on = j["keys"]
        if "left" not in on or "right" not in on:
            raise ConfigError(f"[{name}] wide.joins[{tbl}].keys 缺少 left/right")
        if on["left"] not in wide_cols:
            raise ConfigError(f"[{name}] join 左键 {on['left']} 不在主表 {main} 字段中")
        if on["right"] not in inst.columns_of(tbl):
            raise ConfigError(f"[{name}] join 右键 {on['right']} 不在 {tbl} 字段中")
        for c in j.get("columns", []):
            if c not in inst.columns_of(tbl):
                raise ConfigError(f"[{name}] join 引用列 {tbl}.{c} 未在字段契约中声明")
            if c in wide_cols:
                raise ConfigError(f"[{name}] join 列 {c} 与主表列冲突（需在源配置中改名）")
            wide_cols.add(c)
    for d in wide.get("derived", []):
        if "name" not in d or "expr" not in d:
            raise ConfigError(f"[{name}] wide.derived[{d.get('name', '?')}] 缺少 name/expr")
        wide_cols.add(d["name"])

    # 维度列必须在宽表可见列中
    for dim in inst.dimensions:
        if dim["column"] not in wide_cols:
            raise ConfigError(f"[{name}] 维度 [{dim['name']}] 引用列 {dim['column']} 不在宽表中")

    # 派生列/指标 expr 的标识符启发式校验（P-07：常见断链在装配期拦下，而非 dbt build 期）
    import re
    _SQL_KEYWORDS = {"sum", "count", "distinct", "round", "nullif", "coalesce", "null",
                     "cast", "as", "date_trunc", "abs", "min", "max", "avg", "case",
                     "when", "then", "else", "end", "and", "or", "not", "in", "true", "false"}
    for d in wide.get("derived", []):
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", d["expr"])) - _SQL_KEYWORDS
        dangling = sorted(t for t in tokens if t not in wide_cols)
        if dangling:
            raise ConfigError(f"[{name}] 派生列 [{d['name']}] 引用了宽表不存在的列: {dangling}")
    for m in inst.metrics:
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m["expr"])) - _SQL_KEYWORDS
        dangling = sorted(t for t in tokens if t not in wide_cols)
        if dangling:
            raise ConfigError(f"[{name}] 指标 [{m['name']}] 引用了宽表不存在的列: {dangling}")

    # 报表引用的指标/维度必须存在；time_dim 若为时间维度必须声明
    for rep in inst.dashboard.get("reports", []):
        for m in rep.get("metrics", []):
            inst.metric(m)
        inst.dimension(rep["dimension"])
        for fd in rep.get("filters", []):
            inst.dimension(fd)
        if rep.get("time_dim"):
            td = inst.dimension(rep["time_dim"])
            if td.get("type") != "time":
                raise ConfigError(f"[{name}] 报表 {rep['key']} 的 time_dim [{rep['time_dim']}] 不是时间维度")

    # 报表分层（base）：上级存在、无环、深度 ≤6、分层报表不声明 filters
    base_of = {r["key"]: r.get("base") for r in inst.dashboard.get("reports", []) if r.get("base")}
    keys = {r["key"] for r in inst.dashboard.get("reports", [])}
    for k, b in base_of.items():
        if b not in keys:
            raise ConfigError(f"[{name}] 报表 {k} 的 base [{b}] 不存在")
        rep = next(r for r in inst.dashboard.get("reports", []) if r["key"] == k)
        if rep.get("filters"):
            raise ConfigError(f"[{name}] 分层报表 {k} 不支持 filters（筛选维度固定为分组/时间维度）")
    for k in base_of:
        seen, cur = set(), k
        while cur in base_of:
            if cur in seen:
                raise ConfigError(f"[{name}] 报表分层出现环: {k}")
            seen.add(cur)
            cur = base_of[cur]
        if len(seen) > 6:
            raise ConfigError(f"[{name}] 报表 {k} 分层深度超过 6 层")

    return inst


def list_instances() -> list[str]:
    """正式账套清单。下划线开头（_t_* / _c2_*）为测试副本约定，永不视为正式账套。"""
    return sorted(p.parent.name for p in INSTANCES_DIR.glob("*/instance.yml")
                  if not p.parent.name.startswith("_"))
