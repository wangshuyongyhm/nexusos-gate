"""检查类型: file_size — 检查一组文件总大小是否 ≥ 阈值。
C7 用。防"空提交/占位提交"(改了 1 字节就算完成)。
"""
import ast
import os
from pathlib import Path

try:
    import _gitcmd
except ImportError:
    from . import _gitcmd


def _coerce_files(value, context: dict) -> list:
    """规整成 list[str]。处理 engine 把 list 占位符转 str 的情况。"""
    if value is None:
        v = context.get("changed_files") or []
    else:
        v = value
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str):
        s = v.strip()
        if not s or "{" in s:
            cv = context.get("changed_files") or []
            return [str(x) for x in cv if x] if isinstance(cv, list) else []
        if s.startswith("[") and s.endswith("]"):
            try:
                p = ast.literal_eval(s)
                if isinstance(p, list):
                    return [str(x) for x in p if x]
            except Exception:
                pass
            inner = s.strip("[]").strip()
            if not inner:
                return []
            return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        return [s]
    return [str(v)] if v else []


def _git_changed_files(project_root: str) -> list:
    """Task387 gate fallback: changed_files 空时,从 git diff --name-only HEAD 拿。
    与 git_diff_scope.py 同模式（不依赖手填 changed_files）。
    失败时返回空列表(让上层判定)。
    """
    if not project_root:
        return []
    # Task1552 S2: 收口 _gitcmd（quotePath 统一）。语义保持 Task524 P1-4a：
    # staged + 排除删除（原 git diff HEAD 三重坑：含 unstaged / 删除文件存在性必挂 /
    # 中文路径 quotePath 引号致 found=0，纯删除 commit 被误 REJECT）。
    rc, out, _ = _gitcmd.run_git(
        ["diff", "--cached", "--name-only", "--diff-filter=d"], project_root
    )
    if rc == 0:
        return [line.strip() for line in out.splitlines() if line.strip()]
    # rc=128 可能是 not a git repo / 无 HEAD,尝试 status
    if rc == 128:
        rc2, out2, _ = _gitcmd.run_git(
            ["status", "--porcelain", "--untracked-files=no"], project_root
        )
        if rc2 == 0:
            return [line[3:].strip() for line in out2.splitlines() if line.strip()]
    return []


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      files: 文件列表(YAML 中 {changed_files})
      min_total_kb: 最小总 KB(默认 1)
      project_root: 文件路径相对根(可选)
    返回: (passed, detail)

    Task387 gate fallback(2026-07-31): 当 files/changed_files 都空时,
    自动从 git diff --name-only HEAD 取（与 git_diff_scope.py 同模式),
    不再直接 fail "无 changed_files"。
    """
    files = _coerce_files(params.get("files"), context)
    min_kb = params.get("min_total_kb", 1)
    project_root = params.get("project_root") or context.get("project_root") or ""
    if isinstance(project_root, str) and "{" in project_root:
        project_root = context.get("project_root", "")

    # Task387 fallback: changed_files 空时,从 git diff 自动取
    if not files and project_root:
        files = _git_changed_files(project_root)
        if not files:
            # git 也拿不到(非 git repo / 无改动) → 跳过检查(偏向 WARN 不卡)
            return True, "无 changed_files 且 git diff 无改动,跳过 file_size 检查"

    if not files:
        # 既无 changed_files 又无 project_root 兜底,跳过(原行为是 fail,改为 skip)
        return True, "无 changed_files 且无 project_root 兜底,跳过 file_size 检查"

    total = 0
    found = 0
    missing = []
    missing_abs = []  # Task519: 实际检查的绝对路径（0-found 诊断用）
    for f in files:
        p = Path(f).expanduser()
        if not p.is_absolute() and project_root:
            p = Path(project_root) / f
        if p.exists() and p.is_file():
            try:
                total += p.stat().st_size
                found += 1
            except OSError:
                missing.append(f)
                missing_abs.append(str(p))
        else:
            missing.append(f)
            missing_abs.append(str(p))

    total_kb = total / 1024.0
    passed = total_kb >= min_kb and found > 0

    if not passed:
        if found == 0:
            import os
            return False, (
                f"0 个文件存在(共 {len(files)} 个声明): {missing[:3]} "
                f"| 实查路径: {missing_abs[:3]} | cwd={os.getcwd()} project_root={project_root!r}"
            )
        return False, (
            f"总大小 {total_kb:.2f}KB < 阈值 {min_kb}KB "
            f"({found}/{len(files)} 个文件存在)"
        )
    return True, (
        f"总大小 {total_kb:.2f}KB ≥ {min_kb}KB "
        f"({found}/{len(files)} 个文件)"
    )
