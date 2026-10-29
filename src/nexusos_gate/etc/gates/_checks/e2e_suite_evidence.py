"""检查类型: e2e_suite_evidence — G18 NEXUS 系统改动 e2e 复测证据（Task1536）。

用户定向 09240901："串联复测全绿+并发压测零破坏——以后 NEXUS 系统涉及的修改
都要做的流程"。本插件把它机器化：done 回调时判定任务是否系统改动单，是则查
report/产出中的 e2e-suite 运行证据。

判定链（配置单一源 $NEXUS_HOME/gate/e2e-paths.yaml 用户文件，1959 单3 起
包内 etc/ 不再携带 vault 相对路径；无配置=WARN skip——「配置单一源勿在代码
加路径」原则不变，落点迁移）：
  1. files[] 命中 system_path_patterns 任一 → 系统改动单
  2. 任务书（input/task.md 或 dispatched 副本）含 read_only_markers 任一
     且 files[] 未命中系统路径 → 只读复测单，豁免
  3. 任务书含 worktree 契约段 且 正文含 task_md_system_markers → 系统改动单
     （文件列表未列施工路径时的兜底信号）
  4. 其余 → 豁免（纯文档/纯数据单不拦，任务书陷阱1）

证据链（系统改动单时）：
  - report.md yaml 机读块含 e2e_suite: pass → 过
  - report.md 正文含 run-suite 运行痕迹（run-suite.sh --quick/--stress + 全绿/pass）
    → 过
  - output/files/ 下有 *e2e* 日志文件 → 过
  - 套件入口不存在（Task1535 过渡期）→ 不过，detail 注明"套件未就位"（WARN 语义）
  - 无任何证据 → 不过（WARN；跑稳一周后可升 REJECT，循 C13 先例）

severity 起步 WARN（done.yaml 注册处控制）——本插件只返回事实。
"""
import os
import re
from pathlib import Path

import nexusos_common as _nxc
import yaml

try:
    import _vaultlink
except ImportError:
    from . import _vaultlink

_WORKTREE_RE = re.compile(r"worktree\s*契约", re.IGNORECASE)
_YAML_BLOCK_RE = re.compile(r"```yaml(.*?)```", re.DOTALL)
_RUNSUITE_RE = re.compile(r"run-suite\.sh[^`\n]{0,80}(--quick|--stress|全绿|passed|✅)|e2e[_-]suite[:：]\s*(pass|true|全绿)", re.IGNORECASE)


_CFG_CANDIDATES_HELP = "$NEXUS_HOME/gate/e2e-paths.yaml（或 env NEXUS_GATE_E2E_PATHS 直指）"


def _load_cfg(context: dict | None = None) -> dict:
    """配置解析（1959 单3，design §5 剥离行）：

    env NEXUS_GATE_E2E_PATHS > $NEXUS_HOME/gate/e2e-paths.yaml（用户文件，
    NEXUS_HOME 单源 nexusos-common）> 缺失 → {}（check 层 WARN skip，不再读
    包内 vault 相对 etc/e2e-paths.yaml——示例已移 etc/checks/examples/）。
    值支持 ${NEXUS_ROOT}/${NEXUS_HOME} 占位展开（vault 不可得时留痕
    原样，由 check 层 WARN skip 兜住）。
    """
    p = None
    env_path = os.environ.get("NEXUS_GATE_E2E_PATHS", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
    else:
        p = _nxc.subpath("gate", "e2e-paths.yaml")
    if not p.is_file():
        return {}
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    root = ""
    if context:
        root = str(context.get("vault_root") or "")
    if not root:
        root = str(_nxc.vault_root() or "")
    if root:
        cfg = {k: _expand(v, root) for k, v in cfg.items()}
    return cfg


def _expand(value, vault_root: str):
    """cfg 值占位展开（str 递归进 list；vault 缺失时占位留痕）。"""
    if isinstance(value, str):
        out = value.replace("${NEXUS_ROOT}", vault_root)
        out = out.replace("${NEXUS_HOME}", str(_nxc.nexus_home()))
        return out
    if isinstance(value, list):
        return [_expand(v, vault_root) for v in value]
    return value


def _match_any(path: str, patterns) -> bool:
    import fnmatch
    p = (path or "").lstrip("./")
    return any(fnmatch.fnmatchcase(p, pat) for pat in patterns)


def _task_dir_of(task_path: str) -> Path:
    p = Path(task_path)
    if p.is_dir():
        return p
    return p.parent.parent


def _read_task_md(task_dir: Path) -> str:
    """任务书正文：input/task.md 优先，否则任一 dispatched 副本（G14 同款口径）。"""
    primary = task_dir / "input" / "task.md"
    if primary.is_file():
        return primary.read_text(encoding="utf-8", errors="replace")
    for f in sorted((task_dir / "input").glob("task.dispatched.*.md")):
        return f.read_text(encoding="utf-8", errors="replace")
    return ""


def check(params: dict, context: dict, agent: str) -> tuple:
    cfg = _load_cfg(context)
    sys_pats = cfg.get("system_path_patterns", [])
    ro_markers = cfg.get("read_only_markers", [])
    md_markers = cfg.get("task_md_system_markers", [])
    suite_entry = cfg.get("suite_entry", "")

    # 1959 剥离：无用户配置 → WARN skip 非 fail（design §5「无配置=WARN skip 非 REJECT」；
    # 3 元组 T670 协议降 severity，G18 的 REJECT 只在配置在场时生效）
    if not sys_pats or not suite_entry:
        return False, (
            f"e2e_suite_evidence: 未配置 e2e-paths（预期 {_CFG_CANDIDATES_HELP}；"
            f"包内示例见 etc/checks/examples/e2e-paths.yaml）——WARN skip"
        ), "WARN"

    vault = Path(str(context.get("vault_root") or _vaultlink.vault_root()))
    files = context.get("files") or []
    if isinstance(files, str):
        files = [files]

    # --- 判定 1：files[] 命中系统路径 ---
    hit = [f for f in files if _match_any(str(f), sys_pats)]
    task_path = context.get("task_path") or ""
    task_dir = _task_dir_of(task_path) if task_path else None
    task_md = _read_task_md(task_dir) if task_dir else ""

    if hit:
        reason = f"files 命中系统路径（如 {hit[0]}）"
    else:
        # --- 判定 2：只读复测单豁免 ---
        if task_md and any(m in task_md for m in ro_markers):
            return True, "非系统改动单（任务书明示只读复测/零改动，G18 豁免）"
        # --- 判定 3：worktree 契约 + 任务书系统路径字样兜底 ---
        if task_md and _WORKTREE_RE.search(task_md) and any(m in task_md for m in md_markers):
            reason = "任务书含 worktree 契约+系统路径字样（files 未列施工路径的兜底信号）"
        else:
            # --- 判定 4：豁免 ---
            return True, "非系统改动单（改动面未命中 e2e-paths.yaml 系统路径模式）"

    # --- 系统改动单：查 e2e 证据 ---
    suite_ok = (vault / suite_entry).exists()
    report = task_dir / "output" / "report.md" if task_dir else None
    report_text = report.read_text(encoding="utf-8", errors="replace") if report and report.is_file() else ""

    evidence = []
    for block in _YAML_BLOCK_RE.findall(report_text):
        if re.search(r"e2e_suite\s*:\s*(pass|true)", block, re.IGNORECASE):
            evidence.append(f"report yaml 块 e2e_suite:pass（{report.name}）")
    if _RUNSUITE_RE.search(report_text):
        evidence.append("report 正文含 run-suite 运行痕迹")
    if task_dir:
        for f in sorted((task_dir / "output" / "files").glob("*e2e*")):
            if f.is_file():
                evidence.append(f"运行日志 {f.name}")
                break

    if evidence:
        return True, f"系统改动单（{reason}）e2e 证据：{'；'.join(evidence[:2])}"

    if not suite_ok:
        return False, (f"系统改动单（{reason}）但无 e2e 证据——套件未就位"
                       f"（{suite_entry} 不存在，Task1535 过渡期 WARN 语义；done 后补跑或 report 记录跳过原因）")
    return False, (f"系统改动单（{reason}）但无 e2e 证据——quickref 3F：done 前跑 "
                   f"`bash {suite_entry} --quick` 全绿（并发敏感面加 --stress），证据写 report yaml 块 e2e_suite: pass")
