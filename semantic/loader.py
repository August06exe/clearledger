# -*- coding: utf-8 -*-
"""语义引擎（通用，零业务预设）：五配置加载与交叉校验"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INSTANCES_DIR = ROOT / "instances"

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
    """加载实例五配置并做交叉引用校验。任何引用悬空立即报错——fail fast。"""
    d = INSTANCES_DIR / name
    if not d.exists():
        raise ConfigError(f"实例不存在: {d}")

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

    # ---- 交叉引用校验 ----
    wide = inst.wide.get("wide", {})
    main = wide.get("main")
    if not main:
        raise ConfigError(f"[{name}] wide.yml 缺少 main")
    inst.source(main)  # 存在性

    wide_cols: set[str] = set(inst.columns_of(main))
    for j in wide.get("joins", []):
        tbl = j["table"]
        inst.source(tbl)
        on = j["keys"]
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

    # 维度列必须在宽表可见列中
    for dim in inst.dimensions:
        if dim["column"] not in wide_cols:
            raise ConfigError(f"[{name}] 维度 [{dim['name']}] 引用列 {dim['column']} 不在宽表中")

    # 报表引用的指标/维度必须存在；time_dim 若为时间维度必须声明
    for rep in inst.dashboard.get("reports", []):
        for m in rep.get("metrics", []):
            inst.metric(m)
        inst.dimension(rep["dimension"])
        if rep.get("time_dim"):
            td = inst.dimension(rep["time_dim"])
            if td.get("type") != "time":
                raise ConfigError(f"[{name}] 报表 {rep['key']} 的 time_dim [{rep['time_dim']}] 不是时间维度")

    return inst


def list_instances() -> list[str]:
    return sorted(p.parent.name for p in INSTANCES_DIR.glob("*/instance.yml"))
