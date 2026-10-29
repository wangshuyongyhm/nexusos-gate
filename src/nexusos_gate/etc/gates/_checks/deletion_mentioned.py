"""检查类型: deletion_mentioned — git diff 有删除行时,commit_msg 要提到删除。
C4 用。设计原则:有删除代码但 commit_msg 完全没提"删/移除/remove"等关键词 → REJECT。
"""
import re

try:
    import _gitcmd
except ImportError:
    from . import _gitcmd

# commit_msg 里视为"提到了删除"的关键词(中英)
# Task508: 增加覆盖语义措辞——文件被重新生成/更新覆盖时产生删除行，
# commit_msg 用"更新/覆盖/刷新/重写"等词隐含"旧内容被替换"，不应拦
MENTION_KEYWORDS = re.compile(
    r"删|移除|去除|去掉|清理|废弃|deprecate?|remove[ds]?|deleted?|drop|dropped|"
    r"strip|cleanup|rip out|rip-out|"
    r"更新|覆盖|刷新|重写|重新生成|入库|重置|替换|迁移",
    re.IGNORECASE,
)


def _git_diff_stat(cwd: str) -> tuple:
    """取 staged diff --numstat,返回 (rc, stdout, stderr)。每行:增 删 文件。

    🔴 08040834 修复：原用 `git diff HEAD`（含 unstaged 工作区改动），
    导致 commit-msg hook 每次都把未 stage 的 M 文件算进删除统计 → 误报。
    C4 应该只检查「即将提交的 staged 改动」，改用 `git diff --cached`。
    Task1552 S2: git 调用收口 _gitcmd（quotePath 统一，numstat 路径不再八进制转义）。
    """
    return _gitcmd.run_git(["diff", "--cached", "--numstat"], cwd)


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      commit_msg: 提交信息(必填)
      project_root: git 仓库根
    返回: (passed, detail)
    """
    project_root = params.get("project_root") or context.get("project_root") or "."
    if isinstance(project_root, str) and "{" in project_root:
        project_root = context.get("project_root", ".")

    commit_msg = params.get("commit_msg") or context.get("commit_msg") or ""
    if isinstance(commit_msg, str) and "{" in commit_msg:
        commit_msg = context.get("commit_msg", "")

    rc, out, err = _git_diff_stat(project_root)
    if rc == 128 and "not a git repository" in (err or "").lower():
        return True, "非 git 仓库,跳过"
    if rc not in (0, 128):
        return True, f"git diff 失败(rc={rc}),跳过"

    # numstat: 每行 "added deleted filepath"(二进制文件是 -\t-\t)
    total_deleted = 0
    deleted_files = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, fname = parts[0], parts[1], parts[2]
        try:
            d = int(deleted)
        except ValueError:
            continue  # 二进制等
        if d > 0:
            total_deleted += d
            deleted_files.append((fname, d))

    if total_deleted == 0:
        return True, "无删除行,通过"

    # 有删除 → 检查 commit_msg 是否提到删除
    if not commit_msg:
        return False, f"删除了 {total_deleted} 行,但 commit_msg 为空"

    if MENTION_KEYWORDS.search(commit_msg):
        return True, (
            f"删除 {total_deleted} 行,commit_msg 已提及 "
            f"(样本: {deleted_files[:3]})"
        )
    return False, (
        f"删除了 {total_deleted} 行({len(deleted_files)} 个文件),"
        f"但 commit_msg 未提及删除/移除: '{commit_msg[:60]}'"
    )
