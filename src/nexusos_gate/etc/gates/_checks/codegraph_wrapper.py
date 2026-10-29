#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codegraph_wrapper.py — Task448 L1 核心：封装 codegraph CLI 调用。

提供 codegraph impact / callers 的 Python 接口。
fail-open 设计：codegraph 不可用/符号未索引 → 返 []，不抛异常（不阻断 gate）。

Task449：新增 check() 函数，挂进 dispatch gate D6_IMPACT。
契约：def check(params, context, agent) -> (passed: bool, detail: str)
"""
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

# codegraph 项目根：1959 单3 起不再 parents[N] 推导（安装形状假设，audit §1 行13），
# 发现策略单源 _workspace_root（显式参数 > NEXUS_CODEGRAPH_PROJECT > NEXUS_ROOT
# 布局探测 > git repo root > None→fail-open []）。
try:
    import _workspace_root
except ImportError:
    from . import _workspace_root
_CODEGRAPH_TIMEOUT = 30  # 兜底，codegraph 查询正常应秒级

# 兜底解析 task.md 时的符号过滤：常见英文非符号词（介词/常用动词/虚词）
# 命中即跳过；准确率不追求 100%，仅 frontmatter 缺失时的兜底
_NON_SYMBOL_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "have", "has",
    "are", "was", "were", "will", "would", "should", "must", "shall", "can",
    "may", "might", "could", "true", "false", "none", "null", "task", "todo",
    "note", "notes", "warning", "error", "info", "debug", "trace", "log",
    "all", "any", "new", "old", "set", "get", "put", "post", "use", "via",
}


def _run_codegraph(subcmd: str, symbol: str, project_dir: Optional[str] = None) -> dict:
    """通用 codegraph CLI 调用。

    Args:
        subcmd: "impact" / "callers"
        symbol: 符号名
        project_dir: codegraph 项目根（缺省=_workspace_root 发现策略）
    Returns:
        解析后的 JSON dict，失败返 {}
    """
    pd = project_dir or _workspace_root.resolve_workspace_root()
    if pd is None:
        return {}  # 工作区根不可得（干净环境无 vault 无 git）——fail-open 同「不可用」
    cmd = ["codegraph", subcmd, symbol, "-j", "-p", str(pd)]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=_CODEGRAPH_TIMEOUT, check=False,
        )
        if r.returncode != 0:
            return {}
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def scan_symbol_impact(symbol: str, project_dir: Optional[str] = None) -> list:
    """调 codegraph impact，返回受影响的符号清单。

    Args:
        symbol: 符号名（函数/方法/类）
        project_dir: codegraph 项目根
    Returns:
        [{"name":..., "kind":..., "filePath":..., "startLine":...}, ...]
        codegraph 不可用或符号未索引 → 返 []（fail-open）
    """
    data = _run_codegraph("impact", symbol, project_dir)
    return data.get("affected", []) if isinstance(data, dict) else []


def scan_symbol_callers(symbol: str, project_dir: Optional[str] = None) -> list:
    """调 codegraph callers，返回直接调用方清单。

    Returns:
        [{"name":..., "kind":..., "filePath":..., "startLine":...}, ...]
    """
    data = _run_codegraph("callers", symbol, project_dir)
    return data.get("callers", []) if isinstance(data, dict) else []


# ============================================================================
# Task449: D6_IMPACT check 函数（挂 dispatch gate）
# ============================================================================

def _extract_symbols_from_frontmatter(task_md_text: str) -> list:
    """从 task.md 文本提取 frontmatter 的 impact_symbols（正则，不引入新依赖）。

    匹配: impact_symbols: [verify_credential, issue_orchestrator_search_cred]
    或:   impact_symbols: []（返 []）
    """
    m = re.search(
        r"^impact_symbols:\s*\[([^\]]*)\]",
        task_md_text,
        re.MULTILINE,
    )
    if not m:
        return []
    raw = m.group(1).strip()
    if not raw:
        return []
    # YAML list 元素分割：逗号 + 可选引号
    items = [x.strip().strip("\"'") for x in raw.split(",")]
    return [x for x in items if x]


def _extract_symbols_from_body(task_md_text: str) -> list:
    """兜底：frontmatter 无 impact_symbols 时，从正文提符号候选。

    策略：
      1. 反引号包裹的标识符 `verify_credential`（最可靠）
      2. "改动点N" 列表项后的标识符
    过滤：
      - 必须 [a-z_][a-z0-9_]{2,}（>=3 字符）
      - 排除常见虚词/介词（_NON_SYMBOL_WORDS）
    """
    candidates = set()

    # 1. 反引号包裹的标识符
    for m in re.finditer(r"`([a-z_][a-z0-9_]{2,})`", task_md_text):
        candidates.add(m.group(1))

    # 2. 列表项首标识符："1. verify_credential ..." / "1、 verify_credential"
    for m in re.finditer(r"^\s*[0-9]+[.、)]\s*([a-z_][a-z0-9_]{2,})", task_md_text, re.MULTILINE):
        candidates.add(m.group(1))

    # 过滤虚词
    return [s for s in candidates if s not in _NON_SYMBOL_WORDS]


def _task_md_mentions_path(task_md_text: str, file_path: str) -> bool:
    """检查 task.md 正文是否提及该 file_path 或其文件名。

    codegraph 返回的 filePath 形如 "nexus/api_server.py"（相对自动化脚本/）。
    任务书可能写：
      - 完整路径 "nexus/api_server.py"
      - 文件名 "api_server.py"
      - 文件 stem "api_server"
    任一出现即视为 covered。
    """
    if not file_path:
        return False
    # 全 path
    if file_path in task_md_text:
        return True
    # 文件名
    fname = file_path.rsplit("/", 1)[-1]
    if fname and fname in task_md_text:
        return True
    # stem（去 .py 后缀）
    stem = fname.rsplit(".", 1)[0] if "." in fname else fname
    if stem and len(stem) >= 4 and stem in task_md_text:
        return True
    return False


def check(params: dict, context: dict, agent: str) -> tuple:
    """D6_IMPACT: dispatch 前关联性检查（改 A 漏 B 防护）。

    流程：
      1. 取 symbols（Z 方案）：
         - 优先 {task_dir}/input/task.md frontmatter impact_symbols
         - frontmatter 空 → 解析 task.md 正文（反引号/列表项）兜底
      2. 对每个 symbol 调 scan_symbol_impact
      3. 每个引用点 affected[] 检查：filePath 在 task.md 正文出现 → covered
         未出现 → uncovered
      4. uncovered 超阈值 → (False, ...)
      5. codegraph 故障 / 符号查无结果 → 放行（fail-open）

    params:
      max_uncovered: 允许的未覆盖点数，默认 0（严格）
      ignore_symbols: 跳过的符号清单（通用名，本阶段可空）
    context:
      task_dir: 任务目录（必用，task.md 在 {task_dir}/input/task.md）
      task_id / target_agent: 备用
    """
    max_uncovered = params.get("max_uncovered", 0)
    ignore_symbols = set(params.get("ignore_symbols", []) or [])

    task_dir = context.get("task_dir", "")
    if not task_dir:
        return True, "无 task_dir，跳过 D6_IMPACT"

    task_md_path = Path(task_dir) / "input" / "task.md"
    if not task_md_path.exists():
        return True, f"task.md 不存在: {task_md_path}，跳过 D6_IMPACT"

    try:
        task_md_text = task_md_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return True, f"task.md 读取失败（跳过）: {e}"

    # 取 symbols：frontmatter 优先，正文兜底
    symbols = _extract_symbols_from_frontmatter(task_md_text)
    symbols_source = "frontmatter"
    if not symbols:
        symbols = _extract_symbols_from_body(task_md_text)
        symbols_source = "body-fallback"

    # 过滤 ignore
    symbols = [s for s in symbols if s not in ignore_symbols]

    if not symbols:
        return True, "未提取到任何 impact_symbols（frontmatter 和正文都无），跳过 D6_IMPACT"

    # 对每个 symbol 调 impact，攒 uncovered
    uncovered = []
    symbols_with_hits = 0
    for sym in symbols:
        try:
            affected = scan_symbol_impact(sym)
        except Exception:
            # 单 symbol 扫描异常不阻塞其他 symbol
            continue
        if not affected:
            # 查无结果 → 当 covered（陷阱 3：可能是新符号未 index）
            continue
        symbols_with_hits += 1
        for item in affected:
            file_path = item.get("filePath", "")
            if not _task_md_mentions_path(task_md_text, file_path):
                uncovered.append({
                    "symbol": sym,
                    "filePath": file_path,
                    "name": item.get("name", ""),
                    "startLine": item.get("startLine", 0),
                })

    # 全部 symbols 都查无结果 → 当 covered（陷阱 3）
    if symbols_with_hits == 0:
        return True, (
            f"D6_IMPACT: 提取到 {len(symbols)} 个符号（{symbols_source}）但 codegraph 全部查无结果"
            f"（可能未 index 或 codegraph 不可用），跳过"
        )

    if len(uncovered) > max_uncovered:
        # 取前 5 个 uncovered 写进 detail
        preview = uncovered[:5]
        detail_lines = [
            f"D6_IMPACT: {len(uncovered)} 个关联点未在任务书体现"
            f"（{len(symbols)} symbols from {symbols_source}, max_uncovered={max_uncovered}）"
        ]
        for u in preview:
            detail_lines.append(
                f"  - symbol={u['symbol']}, file={u['filePath']}:{u['startLine']} ({u['name']})"
            )
        if len(uncovered) > 5:
            detail_lines.append(f"  ...等 {len(uncovered)} 个")
        return False, "\n".join(detail_lines)

    # 通过（含完全 covered 和 uncovered 在阈值内两种）
    if uncovered:
        return True, (
            f"D6_IMPACT: {len(uncovered)} 个 uncovered 在 max_uncovered={max_uncovered} 内"
            f"（{len(symbols)} symbols from {symbols_source}）"
        )
    return True, (
        f"D6_IMPACT: 全部 {symbols_with_hits} 个有 impact 结果的符号的关联点"
        f"都在任务书体现（{len(symbols)} symbols from {symbols_source}）"
    )


if __name__ == "__main__":
    # 自测
    import sys
    test_sym = sys.argv[1] if len(sys.argv) > 1 else "verify_credential"
    print(f"=== impact {test_sym} ===")
    for x in scan_symbol_impact(test_sym):
        print(f"  {x['kind']:10} {x['name']:30} {x['filePath']}:{x['startLine']}")
    print(f"=== callers {test_sym} ===")
    for x in scan_symbol_callers(test_sym):
        print(f"  {x['kind']:10} {x['name']:30} {x['filePath']}:{x['startLine']}")
