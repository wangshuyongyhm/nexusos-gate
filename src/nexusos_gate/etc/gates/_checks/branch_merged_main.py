"""检查类型: branch_merged_main — done gate G15「分支已合并回 main」（Task 1376）。

机制背景：多 Agent 并行曾把修复丢在分支上没人合回（1371 找回 6 组已验收未合功能）。
G15 在 done 回调时对账：任务目录能推出分支名（feat/<任务号>）且集成仓配置可达时，
验 `git merge-base --is-ancestor feat/<N> main`；非 ancestor → WARN（过渡期不 REJECT，
文本提示「先 nexus-wt done 再回调」）。无集成仓/无分支场景跳过。

路径参数化：集成仓 = env NEXUS_WT_REPO > ~/.config/nexus/wt-repo 首行（与 nexus-wt.sh
同一单源），禁硬编码绝对路径。
"""
import os
import re
import subprocess
from pathlib import Path


def _repo() -> str:
    """集成仓路径：env 优先 > 配置文件；都没有返回空串（跳过语义）。"""
    env = os.environ.get("NEXUS_WT_REPO", "").strip()
    if env:
        return env
    cfg = Path.home() / ".config" / "nexus" / "wt-repo"
    try:
        line = cfg.read_text(encoding="utf-8").splitlines()[0].strip()
        return line
    except (OSError, IndexError):
        return ""


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, timeout=15
    )


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: (无特殊参数)
    context: task_path / task_dir（done gate 任一，取 basename 推任务号）
    返回: (passed, detail)
    """
    repo = _repo()
    if not repo or not Path(repo, ".git").exists():
        return True, "无集成仓配置（NEXUS_WT_REPO / ~/.config/nexus/wt-repo），G15 跳过"

    task_dir = context.get("task_path") or context.get("task_dir") or ""
    m = re.match(r"(\d+)", Path(task_dir).name)
    if not m:
        return True, f"任务目录 {Path(task_dir).name or '?'} 推不出任务号，G15 跳过"
    branch = f"feat/{m.group(1)}"

    if _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode != 0:
        return True, f"分支 {branch} 不存在（非 worktree 任务），G15 跳过"
    if _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/main").returncode != 0:
        return True, "集成仓无 main 分支，G15 跳过"

    anc = _git(repo, "merge-base", "--is-ancestor", branch, "main")
    if anc.returncode == 0:
        return True, f"分支 {branch} 已合并回 main"
    return False, (
        f"分支 {branch} 未合并回 main——先在集成仓执行 nexus-wt done {m.group(1)} "
        "再发 done 回调（过渡期 WARN，验证后将升级 REJECT）"
    )
