"""检查类型: task_subgraph_connected — 任务子图连通（G14，09071853 升级为覆盖完整性）。

背景：Task956 的旧 G14 只查任务书「## 产出登记」段标题存在——09071853 实证复发
（1221 个真孤儿中 task 域 837）：小弟有段但漏列文件照样过闸（1177 案：段在但漏
input/references.md、input/process/full-log.md、process/full-log.md 三个）。
本插件把检查升级为两层：① 段存在 ② 任务目录内全部 .md 被任务书 wikilink 覆盖
（图谱语义：完全无边的文件才是孤儿——裸名链接 Obsidian 也能建边，按 basename
匹配算覆盖；路径限定为主形态，task-spec §2 第 8 项 09071853 版）。
1409 豁免补丁：task.dispatched.*.md 副本行写纯文本留痕即可、无需 wikilink——
副本在 done 后被 dispatchd 系统吞噬（池#102 已 11 例），wikilink 只会变成死链，
与 task-spec §2 第 8 项 0917 纯文本铁律统一（镜像 G11 源侧豁免先例）。
"""
import os
from pathlib import Path

try:
    import _vaultlink
except ImportError:
    from . import _vaultlink

REG_TITLE = "## 产出登记"


def _task_dir_of(task_path: str) -> Path:
    """task_path 形态兼容：.../input/task.md 取两级父；直接给目录就用目录。"""
    p = Path(task_path)
    if p.is_dir():
        return p
    return p.parent.parent


def _md_files(task_dir: Path) -> list:
    """任务目录内全部 .md（含 input/output/process 三处，vault 全 walk）。"""
    out = []
    for root, dirs, files in os.walk(task_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".md"):
                out.append(Path(root) / f)
    return out


def _covered(md_abs: Path, task_dir: Path, links: list) -> bool:
    """该文件是否被任一 wikilink 覆盖：路径限定精确匹配，或裸名 basename 匹配。"""
    rel = md_abs.relative_to(task_dir).as_posix()
    rel_noext = rel[:-3] if rel.endswith(".md") else rel
    for t in links:
        t = t.strip()
        if not t:
            continue
        t_noext = t[:-3] if t.endswith(".md") else t
        if "/" in t:  # 路径限定：链接路径（vault 相对）== 文件相对本任务目录或 vault 全路径
            if t in (rel, rel_noext) or t_noext == rel or t == rel_noext:
                return True
            # 任务书常写 vault 全路径（task/NN-xx/...），文件相对任务目录短——按尾段对齐
            if t_noext.endswith("/" + rel) or t_noext.endswith("/" + rel_noext):
                return True
        else:  # 裸名：Obsidian 可解析建边（同名歧义时仍连其一）——按 basename 认覆盖
            if t_noext == md_abs.name[:-3]:
                return True
    return False


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: (无特殊参数)
    context: task_path（done gate 既有字段，.../input/task.md 或任务目录）
    返回: (passed, detail)
    """
    task_path = context.get("task_path", "") or context.get("task_dir", "")
    if not task_path:
        return True, "无 task_path（非任务场景），跳过子图连通校验"

    task_dir = _task_dir_of(task_path)
    if not task_dir.is_dir():
        return True, f"任务目录不存在({task_dir})，跳过"

    # dispatched 副本优先（dispatch 期间小弟读的是副本，登记写在副本上同样有效）
    book = None
    for cand in ("input/task.md",):
        p = task_dir / cand
        if p.is_file():
            book = p
            break
    if book is None:
        disp = sorted((task_dir / "input").glob("task.dispatched.*.md")) if (task_dir / "input").is_dir() else []
        book = disp[0] if disp else None
    if book is None:
        return True, f"任务书不存在({task_dir}/input/)，跳过（G1/D1 域）"

    text = book.read_text(encoding="utf-8", errors="ignore")
    # 段头宽松匹配（1401-w1b）：任务书模板存在带后缀变体（如「## 产出登记
    # （done 前填）」），原精确 in 匹配漏检 → 误报"无产出登记段"（1401-w2
    # 实测复现）。startswith 认定：段头以 REG_TITLE 起始即算，后缀任意。
    if not any(ln.strip().startswith(REG_TITLE) for ln in text.split("\n")):
        return False, (
            f"任务书无「{REG_TITLE}」段（含变体段头）——task-spec §2 第 8 项：done 前任务书尾部"
            "追加产出登记段（路径限定 wikilink 列任务目录全部 .md；无 .md 产出可声明式空段）"
        )

    links = _vaultlink.extract_wikilinks(text)
    # 副本 done 后被系统吞噬，纯文本留痕即合规（1409 与 task-spec 纯文本铁律统一，
    # 豁免写法镜像 G11 no_new_broken_links.py 源侧先例）
    mds = [m for m in _md_files(task_dir)
           if m.name != book.name and ".dispatched." not in m.name]
    missing = [str(m.relative_to(task_dir)) for m in mds if not _covered(m, task_dir, links)]
    if missing:
        shown = ", ".join(missing[:8]) + ("…" if len(missing) > 8 else "")
        return False, (
            f"任务子图不连通：{len(missing)} 个 .md 未被任务书 wikilink 覆盖（{shown}）"
            "——task-spec §2 第 8 项 09071853 版：产出登记需列任务目录全部 .md"
            "（含 input/references.md、input/process/full-log.md 错位产物、process/full-log.md），路径限定"
            "；task.dispatched.*.md 副本行写纯文本留痕即可，无需 wikilink（1409 豁免）"
        )
    return True, f"任务子图连通：{len(mds)} 个 .md 全部被任务书覆盖（登记段+其他链接）"
