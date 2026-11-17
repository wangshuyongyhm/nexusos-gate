#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nexusos-gate — NEXUS 声明式门禁引擎（Task630 三件套首包）。

组成:
  - gate_engine: 场景 YAML 加载 + required_context 校验 + checks 插件分发
  - etc/gates/*.yaml: 场景定义(done/init/dispatch/persist/code/...)
  - etc/gates/_checks/*.py: 检查插件池(启动时按文件名自动发现)

依赖: 仅 pyyaml(硬依赖)。psycopg2 为可选(插件告警写 PG, fail-open)。

旧路径兼容: nexusos_xdr.gate_engine / etc.gates._checks.* 经
nexusos_xdr/ 下的 re-export shim + symlink 继续可用(零破坏)。
"""
__version__ = "1.0.0"


def gate_check(scenario: str, context: dict, agent: str = "") -> dict:
    """过场景门禁（便捷导出，写法对齐 nexusos_xdr.gate_check）。

    延迟 import(函数内)——避免 `import nexusos_gate` 触发插件池全量扫描。
    返回 {passed, failures, hard_fails, warns}。
    """
    from nexusos_gate.gate_engine import check
    return check(scenario, context, agent=agent)
