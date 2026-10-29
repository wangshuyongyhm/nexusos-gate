#!/usr/bin/env python3
"""_workspace_root — 工作区根发现策略（1959 单3，design §5 codegraph 行）。

为什么存在：codegraph_wrapper/complexity_aware 原用 parents[7] 包位置推导
工作区根——安装形状假设（pip 装到陌生环境必错目录，audit §1 行13）。
本助手把发现策略接口化为显式链，杀 parents[N]：

    explicit 参数 > env NEXUS_CODEGRAPH_PROJECT（直指项目根）
    > env NEXUS_ROOT（vault 布局：优先 {vault}/05-System/自动化脚本
      的 .codegraph 私人深链探测，退 {vault} 本身——均在 .codegraph 存在
      才认）> git repo root（从 start 向上找 .git）> None

插件加载形态兼容（同 _gitcmd/_vaultlink 先例）：
    try:    import _workspace_root
    except ImportError: from . import _workspace_root
"""
import os
from pathlib import Path


def _has_codegraph(root: Path) -> bool:
    return (root / ".codegraph").is_dir()


def _vault_candidate(vault: str) -> Path | None:
    """vault 布局下的项目根探测：私人深链（自动化脚本/.codegraph）优先，
    退 vault 根自身；两者都无 .codegraph → None（不认）。"""
    v = Path(vault)
    deep = v / "05-System" / "自动化脚本"
    if _has_codegraph(deep):
        return deep
    if _has_codegraph(v):
        return v
    return None


def resolve_workspace_root(explicit: str | None = None, start: Path | None = None) -> Path | None:
    """工作区根发现（显式链见模块 docstring）。返回 None=不可得（调用方 fail-open）。"""
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_dir() else None
    env_direct = os.environ.get("NEXUS_CODEGRAPH_PROJECT", "").strip()
    if env_direct:
        p = Path(env_direct).expanduser()
        return p if p.is_dir() else None
    env_vault = os.environ.get("NEXUS_ROOT", "").strip()
    if env_vault:
        cand = _vault_candidate(env_vault)
        if cand is not None:
            return cand
    d = (start or Path.cwd()).resolve()
    for p in (d, *d.parents):
        if (p / ".git").exists():
            return p
    return None
