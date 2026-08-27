#!/usr/bin/env python3
"""
kb_tools.py - kb-organizer skill 的确定性辅助工具（随 skill 版本走，见 CHANGELOG.md）

设计原则：能用代码保证正确的事（哈希对比、manifest读写、front-matter抽取）
都放在这里，不要靠模型自己"记得"或"猜"文件有没有变化过。

子命令:
  init            初始化知识库目录骨架 (_meta/manifest.json, _meta/taxonomy.md, _inbox/)
  get-config      读取已保存的交互/处理策略偏好（_meta/config.json），没有就返回found:false
  set-config      保存交互模式(interactive/silent)和处理策略(smart/light/deep)，后续运行复用
  scan            对比源目录与manifest，输出 new/changed/unchanged/deleted 文件列表(JSON)
  update-manifest 处理完一个源文件后，登记它在manifest中的记录（每篇处理完就调用一次，
                   不要攒到最后一起登记，保证中断后可以从断点继续）。落点用可重复的
                   --target 参数传（不是JSON字符串），一篇文档落到几个页面就传几次
  remove-entry    源文件已被删除时，从manifest中移除记录（不会自动删除已生成的知识库页面）
  list-targets    列出某个分类目录下所有已有页面的 front-matter 摘要，同时自动定位并返回
                   taxonomy.md 里这个目录对应的说明/备注——不需要模型另外记得去打开
                   taxonomy.md 查一遍，每次调用这个命令就自动带出来了
  retarget        子目录拆分、挪动已归档页面后，同步更新那些源文件在manifest里的targets记录
                   （只改targets，不动hash/status/title等其它字段，避免误判成"内容变了"）
  create-page     light 模式专用：LLM 只做分类决策，脚本负责创建页面文件（复制源文件
                   正文 + 自动生成 OKF front-matter），省去 LLM 逐行抄写的工作
  quick-classify  light 模式专用：提取源文件的标题、各级标题、首段（不读全文），
                   输出 JSON 供 LLM 做分类决策，省去读整篇文档的开销
  merge-append    light 模式合并专用：把源文件正文追加到已有知识库页面末尾，
                   自动更新目标页面的 sources front-matter，LLM 不读任何文件
  gen-index       为知识库树每一层生成/刷新 index.md（OKF风格：列出子目录+本层页面，
                   各带一句话说明，供不认识本skill的人或其它agent直接浏览）
  log-entry       往知识库根目录 log.md 追加本轮的变更记录（OKF风格：按日期分组的
                   人类可读叙事历史，和 manifest.json 这种机器比对用的记录是两回事）

设计说明3（OKF）：index.md 和 log.md 严格遵循 Google Open Knowledge Format v0.2 约定。
概念页面 front-matter 必须包含 type（必填）、title、description、tags、status、
generated（actor 约定见§7）、sources（每条必须有 resource，可选 id）。gen-index 每次
全量重新生成整棵树（成本很低，只读front-matter不用算hash），不做增量判断。根目录
index.md 带 okf_version: "0.2" front-matter，其他层级不带。index 条目格式为
OKF §8 约定的 `* [Title](url) - description`。log-entry 只做追加，不改写历史条目。

设计说明2：list-targets 原本只返回候选目录下已有页面列表，"要不要检查taxonomy.md里
有没有留过前瞻性备注"完全靠模型自己记得去做，实测下来经常被漏掉——即使备注写对了，
增量运行时也不一定会被翻出来看。现在改成 list-targets 强制要求同时传 --kb-dir，自动
按标题层级去 taxonomy.md 里匹配这个目录对应的条目并把说明/备注一起返回，这样"检查
有没有备注"这件事不再是一个可以被跳过的可选步骤，而是每次调用都会自动发生的事。

设计说明：早期版本里 update-manifest / retarget 的落点是要求传一个JSON数组字符串
（比如 '["a.md","b.md"]'），结果在Windows的cmd/PowerShell下经常因为单引号和JSON内部
双引号互相打架而解析失败，模型解决不了只能去手改manifest.json，风险更大。现在改成
可重复的 --target 参数，全程只用最简单的双引号，不需要在shell里嵌套引号。
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "v10"  # 与 CHANGELOG.md / SKILL.md 头部版本号保持一致


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def load_manifest(meta_dir: Path) -> dict:
    mf = meta_dir / "manifest.json"
    if not mf.exists():
        return {"version": 1, "updated_at": None, "entries": {}}
    with open(mf, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(
            f"❌ {mf} 不是合法 JSON，无法读取（{e}）。\n"
            "这个文件只应该由 kb_tools.py 自己写，如果最近手动编辑过，多半是这里出的问题——"
            "常见原因是多写/少写了一个逗号或引号。可以先用 `python3 -m json.tool "
            f"{mf}` 检查具体哪里错了，改好之后再重试。",
            file=sys.stderr,
        )
        sys.exit(1)


def save_manifest(meta_dir: Path, manifest: dict):
    meta_dir.mkdir(parents=True, exist_ok=True)
    mf = meta_dir / "manifest.json"
    manifest["updated_at"] = now_iso()
    tmp = mf.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    tmp.replace(mf)  # 原子替换，避免半写坏掉manifest


def _parse_taxonomy_blocks(taxonomy_path: Path):
    """把 taxonomy.md 按标题行切成 (level, heading_text, body_text) 的顺序列表。
    约定：## 对应目录深度1（一级分类），### 对应深度2，#### 对应深度3，##### 对应深度4。
    """
    if not taxonomy_path.exists():
        return []
    lines = taxonomy_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    blocks = []
    cur_level, cur_heading, cur_body = None, None, []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading_text = stripped.lstrip("#").strip()
            if cur_heading is not None:
                blocks.append((cur_level, cur_heading, "\n".join(cur_body).strip()))
            cur_level, cur_heading, cur_body = level, heading_text, []
        else:
            cur_body.append(line)
    if cur_heading is not None:
        blocks.append((cur_level, cur_heading, "\n".join(cur_body).strip()))
    return blocks


def find_taxonomy_note(taxonomy_path: Path, category_path: str) -> dict:
    """给定一个相对于kb-dir的目录路径（比如 "01-系统架构/01-fins系统"），
    在taxonomy.md里按标题层级逐级匹配，返回匹配到的最深一级标题的说明/备注文本。
    匹配不到就如实说明匹配到了第几级、卡在哪一段——不要瞎猜返回空结果掩盖过去。
    """
    segments = [s for s in category_path.strip("/").split("/") if s]
    blocks = _parse_taxonomy_blocks(taxonomy_path)
    if not segments:
        return {"found": False, "reason": "empty category path"}
    if not blocks:
        return {"found": False, "reason": "taxonomy.md 不存在或没有任何标题"}

    target_level = 2  # ## 对应第一级
    search_start = 0
    matched_idx = None
    matched_path = []
    parent_level = None  # 已匹配到的父级标题的层级；None 表示还在找最顶层，此时不设边界
    for seg in segments:
        matched_idx = None
        i = search_start
        while i < len(blocks):
            lvl, heading, _ = blocks[i]
            if parent_level is not None and lvl <= parent_level:
                break  # 跑出了当前父级标题的范围（遇到了同级或更高层的标题）
            if lvl == target_level and heading.startswith(seg):
                matched_idx = i
                break
            i += 1
        if matched_idx is None:
            return {
                "found": False,
                "reason": f"在第{target_level - 1}级目录里没找到匹配 \"{seg}\" 的标题",
                "matched_path_so_far": matched_path,
            }
        matched_path.append(blocks[matched_idx][1])
        parent_level = blocks[matched_idx][0]
        search_start = matched_idx + 1
        target_level += 1

    lvl, heading, body = blocks[matched_idx]
    return {"found": True, "matched_heading": heading, "note": body}


TAXONOMY_TEMPLATE = """# 知识库分类目录

> 这个文件是知识库的"分类菜单"。每次分类新文档前先读一遍这个文件。
> 新增顶级分类是"贵"操作，需要人工确认后再加进来，不要在批处理时自动追加。
> 标题层级约定：## 对应一级分类，### 对应它下面的子目录，#### 再下一级，##### 是第四级
> （一般不建议拆到这么深）。`list-targets` 会按这个层级自动匹配对应目录的说明文字，
> 层级写错会导致匹配不到，所以新增/调整标题时要按这个约定来，不要随手加个 #。

## 00-inbox
说明：暂时无法归类、置信度低、或者需要人工判断该不该新建分类的内容，先放这里。
这不是一个正式分类，处理时应优先尝试归入下面的正式分类。

"""


CONFIG_MODES = {
    "interaction_mode": ("interactive", "silent"),
    "processing_mode": ("smart", "light", "deep"),
}


def cmd_get_config(args):
    kb = Path(args.kb_dir)
    cfg_path = kb / "_meta" / "config.json"
    if not cfg_path.exists():
        print(json.dumps({"found": False}, ensure_ascii=False))
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(
            f"❌ {cfg_path} 不是合法 JSON（{e}）。这个文件只应该由 set-config 写，"
            "如果手动改过，用 `python3 -m json.tool` 检查一下具体哪里错了。",
            file=sys.stderr,
        )
        sys.exit(1)
    print(json.dumps({"found": True, **cfg}, ensure_ascii=False))


def cmd_set_config(args):
    kb = Path(args.kb_dir)
    meta = kb / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    cfg = {
        "version": 1,
        "interaction_mode": args.interaction_mode,
        "processing_mode": args.processing_mode,
        "set_at": now_iso(),
    }
    cfg_path = meta / "config.json"
    tmp = cfg_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    tmp.replace(cfg_path)
    print(f"config.json 已更新：interaction_mode={args.interaction_mode}, processing_mode={args.processing_mode}")


def cmd_init(args):
    kb = Path(args.kb_dir)
    meta = kb / "_meta"
    inbox = kb / "_inbox"
    meta.mkdir(parents=True, exist_ok=True)
    inbox.mkdir(parents=True, exist_ok=True)

    manifest_path = meta / "manifest.json"
    if not manifest_path.exists():
        save_manifest(meta, {"version": 1, "entries": {}})
        print(f"created: {manifest_path}")
    else:
        print(f"already exists, left untouched: {manifest_path}")

    taxonomy_path = meta / "taxonomy.md"
    if not taxonomy_path.exists():
        taxonomy_path.write_text(TAXONOMY_TEMPLATE, encoding="utf-8")
        print(f"created: {taxonomy_path}")
    else:
        print(f"already exists, left untouched: {taxonomy_path}")


def cmd_scan(args):
    source = Path(args.source).resolve()
    if not source.exists():
        print(json.dumps({"error": f"source not found: {source}"}, ensure_ascii=False))
        sys.exit(1)

    kb = Path(args.kb_dir)
    meta = kb / "_meta"
    manifest = load_manifest(meta)
    entries = manifest.get("entries", {})

    current_files = {}
    for p in sorted(source.rglob("*.md")):
        rel = str(p.relative_to(source))
        current_files[rel] = p

    result = {"new": [], "changed": [], "unchanged": [], "deleted": []}

    for rel, p in current_files.items():
        h = sha256_of(p)
        prev = entries.get(rel)
        if prev is None:
            result["new"].append({"source": rel, "hash": h})
        elif prev.get("hash") != h:
            result["changed"].append({
                "source": rel,
                "hash": h,
                "old_hash": prev.get("hash"),
                "prev_targets": prev.get("targets", []),
            })
        else:
            result["unchanged"].append({
                "source": rel,
                "hash": h,
                "targets": prev.get("targets", []),
            })

    for rel, prev in entries.items():
        if rel not in current_files:
            result["deleted"].append({"source": rel, "targets": prev.get("targets", [])})

    summary = {k: len(v) for k, v in result.items()}
    print(json.dumps({"summary": summary, **result}, ensure_ascii=False, indent=2))


def cmd_update_manifest(args):
    if not args.target:
        print(
            "❌ 至少要传一个 --target（一篇文档落到几个页面就传几次），例如：\n"
            '  --target "01-系统架构/fins收报模块理解文档.md"\n'
            "如果一篇源文档合并进了多个页面，重复这个参数就行，不需要写JSON、不需要额外加引号。",
            file=sys.stderr,
        )
        sys.exit(1)
    kb = Path(args.kb_dir)
    meta = kb / "_meta"
    manifest = load_manifest(meta)
    entries = manifest.setdefault("entries", {})
    entries[args.source] = {
        "hash": args.hash,
        "status": args.status,
        "targets": list(args.target),
        "title": args.title or "",
        "doc_type": args.doc_type or "",
        "last_processed": now_iso(),
    }
    save_manifest(meta, manifest)
    print(f"updated manifest entry: {args.source} -> status={args.status}, targets={list(args.target)}")


def cmd_remove_entry(args):
    kb = Path(args.kb_dir)
    meta = kb / "_meta"
    manifest = load_manifest(meta)
    entries = manifest.get("entries", {})
    if args.source in entries:
        removed = entries.pop(args.source)
        save_manifest(meta, manifest)
        print(f"removed manifest entry: {args.source} (had targets: {removed.get('targets')})")
    else:
        print(f"no manifest entry found for: {args.source}")


def cmd_retarget(args):
    if not args.target:
        print(
            "❌ 至少要传一个 --target 作为新落点，例如：\n"
            '  --target "01-系统架构/01-fins系统/fins收报模块理解文档.md"\n'
            "挪动后落到多个页面就重复传这个参数。",
            file=sys.stderr,
        )
        sys.exit(1)
    kb = Path(args.kb_dir)
    meta = kb / "_meta"
    manifest = load_manifest(meta)
    entries = manifest.get("entries", {})
    if args.source not in entries:
        print(f"no manifest entry found for: {args.source} (retarget只能用于已登记过的条目)")
        sys.exit(1)
    entries[args.source]["targets"] = list(args.target)
    entries[args.source]["last_processed"] = now_iso()
    save_manifest(meta, manifest)
    print(f"retargeted: {args.source} -> {list(args.target)}")


def cmd_gen_index(args):
    """给整棵知识库树的每一层（有内容的目录）生成/覆盖 index.md，参考 OKF 的
    progressive disclosure 约定：每层列出"子目录"和"本层页面"，各带一句话说明/摘要。
    全量重新生成，不做增量判断——生成成本很低（只读front-matter，不用算hash），
    全量重来最简单也最不容易留下过期信息，跟OKF自己给的示例脚本是一个思路。
    自底向上遍历：只有真正有内容的目录（自己有页面，或者子目录里有内容）才会被
    列进父级的"子目录"清单，避免生成指向空目录（比如还没有任何内容的 _inbox）的死链接。
    """
    kb = Path(args.kb_dir).resolve()
    taxonomy_path = kb / "_meta" / "taxonomy.md"
    written = []
    has_content: dict = {}  # 相对路径(kb-dir下的""表示根) -> 这个目录是否有内容

    for dirpath, dirnames, filenames in os.walk(kb, topdown=False):
        d = Path(dirpath)
        if d.name == "_meta":
            continue  # _meta是脚本自己用的元数据目录，不是知识内容，不进index.md体系

        rel = str(d.relative_to(kb)) if d != kb else ""
        concept_files = sorted(f for f in filenames if f.endswith(".md") and f not in RESERVED_FILENAMES)
        sub_dirs = sorted(
            sd for sd in dirnames
            if has_content.get(f"{rel}/{sd}" if rel else sd, False)
        )

        this_has_content = bool(concept_files) or bool(sub_dirs)
        has_content[rel] = this_has_content
        if not this_has_content:
            continue

        is_root = not rel
        lines_buf = []

        # 根目录 index.md 可带 okf_version frontmatter（§12）
        if is_root:
            lines_buf += ["---", 'okf_version: "0.2"', "---", ""]

        lines_buf.append(f"# {rel if rel else '知识库总览'}")
        lines_buf.append("")

        if rel:
            note = find_taxonomy_note(taxonomy_path, rel)
            if note.get("found") and note.get("note"):
                first_line = note["note"].splitlines()[0]
                if first_line:
                    lines_buf += [f"> {first_line}", ""]

        if sub_dirs:
            lines_buf.append("## 子目录")
            for sd in sub_dirs:
                sub_rel = f"{rel}/{sd}" if rel else sd
                sub_note = find_taxonomy_note(taxonomy_path, sub_rel)
                desc = ""
                if sub_note.get("found") and sub_note.get("note"):
                    desc = sub_note["note"].splitlines()[0]
                entry = f"* [{sd}/]({sd}/index.md)"
                if desc:
                    entry += f" - {desc}"
                lines_buf.append(entry)
            lines_buf.append("")

        if concept_files:
            lines_buf.append("## 页面")
            for cf in concept_files:
                fp = d / cf
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    text = ""
                fm = _parse_front_matter(text)
                title = fm.get("title") or cf[:-3]
                desc = fm.get("description", "")
                entry = f"* [{title}]({cf})"
                if desc:
                    entry += f" - {desc}"
                lines_buf.append(entry)
            lines_buf.append("")

        content = "\n".join(lines_buf).rstrip() + "\n"
        (d / "index.md").write_text(content, encoding="utf-8")
        written.append(str((d / "index.md").relative_to(kb)))

    written.sort()
    print(f"生成/更新了 {len(written)} 个 index.md：")
    for w in written:
        print(f"  {w}")


LOG_HEADER = "# Update Log\n"


def cmd_log_entry(args):
    """往知识库根目录的 log.md 追加本轮运行的变更记录，格式参考 OKF：按日期分组、
    最新的日期在最上面，同一天多次运行就追加到当天的标题下面。这是给人看的叙事性
    历史，不是给脚本比对用的——manifest.json 才是那个角色，两者不重复也不互相替代。
    """
    if not args.entry:
        print(
            "❌ 至少要传一个 --entry（一条变更记录传一次，可重复），例如：\n"
            '  --entry "**Create**: 新建页面 01-系统架构/xxx.md"\n'
            '  --entry "**Ingest**: 处理 3 篇源文档（1 篇新增、2 篇变更）"',
            file=sys.stderr,
        )
        sys.exit(1)

    kb = Path(args.kb_dir)
    log_path = kb / "log.md"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = LOG_HEADER.splitlines()

    date_heading = f"## {today}"
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip() == date_heading:
            insert_idx = i + 1
            break

    new_bullets = [f"* {e}" for e in args.entry]

    if insert_idx is not None:
        lines[insert_idx:insert_idx] = new_bullets
    else:
        header_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("# "):
                header_idx = i + 1
                break
        lines[header_idx:header_idx] = ["", date_heading] + new_bullets

    log_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"log.md 已更新，追加了 {len(args.entry)} 条记录到 {today}")


def _parse_front_matter(text: str) -> dict:
    fm = {}
    if not text.startswith("---"):
        return fm
    end = text.find("\n---", 3)
    if end == -1:
        return fm
    block = text[3:end].strip("\n")
    for line in block.splitlines():
        if ":" in line and not line.strip().startswith("-"):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def _extract_body(text: str) -> str:
    """从 markdown 文件中提取正文（去掉 front-matter 部分）。
    如果没有 front-matter，返回原文。
    """
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    # 跳过 closing --- 和紧随的换行
    body_start = end + 4  # \n--- 是 4 个字符
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    return text[body_start:]


def cmd_create_page(args):
    """light 模式专用：LLM 只做分类决策（定 title/type/description/target），
    脚本负责创建页面文件——复制源文件正文 + 自动生成 OKF front-matter。
    省去 LLM 逐行抄写的工作。
    """
    kb = Path(args.kb_dir)
    source = Path(args.source)
    if not source.exists():
        print(f"❌ 源文件不存在: {source}", file=sys.stderr)
        sys.exit(1)

    source_text = source.read_text(encoding="utf-8", errors="ignore")
    body = _extract_body(source_text)

    # 构建 OKF front-matter
    source_hash = sha256_of(source)
    source_id = Path(args.source).stem
    fm_lines = ["---"]
    fm_lines.append(f"type: {args.type}")
    fm_lines.append(f"title: {args.title}")
    if args.description:
        fm_lines.append(f"description: {args.description}")
    if args.tags:
        fm_lines.append(f"tags: [{args.tags}]")
    if args.category:
        fm_lines.append(f"category: {args.category}")
    fm_lines.append(f"generated: {{ by: kb-organizer/{VERSION}, at: {now_iso()} }}")
    fm_lines.append("sources:")
    fm_lines.append(f"  - id: {source_id}")
    fm_lines.append(f"    resource: {args.source}")
    if args.confidence:
        fm_lines.append(f"confidence: {args.confidence}")
    fm_lines.append("---")
    fm_lines.append("")

    content = "\n".join(fm_lines) + body

    target_path = kb / args.target
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")

    print(json.dumps({
        "created": str(target_path.relative_to(kb)),
        "source": str(args.source),
        "source_hash": source_hash,
        "title": args.title,
        "type": args.type,
    }, ensure_ascii=False, indent=2))


def cmd_quick_classify(args):
    """light 模式专用：提取源文件的元数据（标题、各级标题、首段），不读全文。
    输出 JSON 供 LLM 做分类决策（定 type/title/description/target）。
    """
    source = Path(args.source)
    if not source.exists():
        print(f"❌ 源文件不存在: {source}", file=sys.stderr)
        sys.exit(1)

    text = source.read_text(encoding="utf-8", errors="ignore")
    # 如果有 front-matter，跳过它
    body = _extract_body(text)
    lines = body.splitlines()
    total_lines = len(lines)

    # 提取标题（第一个 # 开头行）和首段
    title = ""
    headings = []
    first_paragraph_lines = []
    max_lines = args.max_lines

    # 第一遍：收集所有 headings + 标题
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped)
            if not title and stripped.startswith("# "):
                title = stripped[2:].strip()

    # 第二遍：提取首段（标题后的第一个非空段落）
    found_heading = False
    in_first_para = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            found_heading = True
            continue
        if not found_heading and stripped == "":
            continue
        if found_heading and stripped == "" and not in_first_para:
            continue  # 跳过标题后的空行
        if found_heading and stripped != "":
            in_first_para = True
        if in_first_para:
            if stripped == "":
                break  # 首段结束
            if len(first_paragraph_lines) < max_lines:
                first_paragraph_lines.append(line)

    # 如果没找到 H1 标题，用文件名
    if not title:
        title = source.stem

    result = {
        "file": str(args.source),
        "title": title,
        "headings": headings[:20],  # 最多 20 个标题，够用
        "first_paragraph": "\n".join(first_paragraph_lines[:max_lines]),
        "total_lines": total_lines,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_merge_append(args):
    """light 模式合并专用：把源文件正文追加到已有知识库页面末尾，
    自动更新目标页面的 sources front-matter。LLM 不读任何文件。
    """
    kb = Path(args.kb_dir)
    source = Path(args.source)
    target = kb / args.target

    if not source.exists():
        print(f"❌ 源文件不存在: {source}", file=sys.stderr)
        sys.exit(1)
    if not target.exists():
        print(f"❌ 目标页面不存在: {target}（merge-append 只能追加到已有页面）", file=sys.stderr)
        sys.exit(1)

    source_text = source.read_text(encoding="utf-8", errors="ignore")
    source_body = _extract_body(source_text)
    source_hash = sha256_of(source)
    source_id = source.stem

    target_text = target.read_text(encoding="utf-8", errors="ignore")

    # 追加内容：用二级标题分隔
    label = args.label or source.stem
    append_block = f"\n\n## 来自 {label}（合并于{datetime.now(timezone.utc).strftime('%Y-%m-%d')}）\n\n{source_body.rstrip()}\n"
    target_text += append_block

    # 更新 front-matter 的 sources 数组：在 sources: 块末尾插入新条目
    fm_end = target_text.find("\n---", 3)
    if fm_end != -1:
        fm_block = target_text[3:fm_end].strip("\n")
        new_entry = f"  - id: {source_id}\n    resource: {args.source}"
        if "sources:" in fm_block:
            # 找到 sources: 行，然后找到这个数组的结束位置（下一个顶层 key）
            fm_lines = fm_block.split("\n")
            insert_idx = None
            in_sources = False
            for i, line in enumerate(fm_lines):
                if line.startswith("sources:"):
                    in_sources = True
                    continue
                if in_sources:
                    # sources 数组内的行以空格开头
                    if line and not line.startswith(" "):
                        insert_idx = i
                        break
            if insert_idx is None:
                # sources 是最后一个 key，追加到末尾
                fm_block += f"\n{new_entry}"
            else:
                fm_lines.insert(insert_idx, new_entry)
                fm_block = "\n".join(fm_lines)
        else:
            fm_block += f"\nsources:\n{new_entry}"
        target_text = "---\n" + fm_block + "\n---" + target_text[fm_end + 4:]

    target.write_text(target_text, encoding="utf-8")

    print(json.dumps({
        "merged_into": str(target.relative_to(kb)),
        "source": str(args.source),
        "source_hash": source_hash,
        "source_id": source_id,
    }, ensure_ascii=False, indent=2))

RESERVED_FILENAMES = {"index.md", "log.md"}


def cmd_list_targets(args):
    cat_dir = Path(args.category_dir)
    pages = []
    if cat_dir.exists():
        for p in sorted(cat_dir.rglob("*.md")):
            if p.name in RESERVED_FILENAMES:
                continue  # index.md/log.md 是保留文件，不是知识页面，不能被当成合并候选
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            fm = _parse_front_matter(text)
            pages.append({
                "path": str(p),
                "title": fm.get("title", ""),
                "description": fm.get("description", ""),
                "type": fm.get("type", ""),
                "tags": fm.get("tags", ""),
                "confidence": fm.get("confidence", ""),
            })

    result = {"pages": pages}

    kb = Path(args.kb_dir)
    taxonomy_path = kb / "_meta" / "taxonomy.md"
    try:
        rel_category = str(cat_dir.resolve().relative_to(kb.resolve()))
    except ValueError:
        result["taxonomy_note"] = {
            "found": False,
            "reason": "category-dir 不在 kb-dir 之下，没法在 taxonomy.md 里定位对应条目，"
                      "检查一下 --category-dir 和 --kb-dir 是不是传反了或者路径没对齐",
        }
    else:
        result["taxonomy_note"] = find_taxonomy_note(taxonomy_path, rel_category)

    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="kb-organizer 辅助工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化知识库目录骨架")
    p.add_argument("--kb-dir", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("get-config", help="读取本知识库已保存的交互/处理策略偏好（首次运行时会没有）")
    p.add_argument("--kb-dir", required=True)
    p.set_defaults(func=cmd_get_config)

    p = sub.add_parser("set-config", help="保存交互/处理策略偏好到 _meta/config.json，后续运行自动复用")
    p.add_argument("--kb-dir", required=True)
    p.add_argument("--interaction-mode", required=True, choices=list(CONFIG_MODES["interaction_mode"]))
    p.add_argument("--processing-mode", required=True, choices=list(CONFIG_MODES["processing_mode"]))
    p.set_defaults(func=cmd_set_config)

    p = sub.add_parser("scan", help="扫描源目录，对比manifest输出 new/changed/unchanged/deleted")
    p.add_argument("--source", required=True)
    p.add_argument("--kb-dir", required=True)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("update-manifest", help="处理完一个源文件后登记它的落点")
    p.add_argument("--kb-dir", required=True)
    p.add_argument("--source", required=True, help="相对于source root的路径，需与scan输出一致")
    p.add_argument("--hash", required=True)
    p.add_argument("--status", required=True, choices=["merged", "new_file", "inbox"])
    p.add_argument("--target", action="append",
                    help='落点路径，一篇文档落到几个页面就传几次这个参数，例如 '
                         '--target "01-a.md" --target "02-b.md"。不用写JSON、不用额外加引号。')
    p.add_argument("--title")
    p.add_argument("--doc-type")
    p.set_defaults(func=cmd_update_manifest)

    p = sub.add_parser("remove-entry", help="源文件已删除时，从manifest中移除记录")
    p.add_argument("--kb-dir", required=True)
    p.add_argument("--source", required=True)
    p.set_defaults(func=cmd_remove_entry)

    p = sub.add_parser("list-targets", help="列出某分类目录下已有页面的front-matter摘要，并自动附带taxonomy.md里对应的说明/备注")
    p.add_argument("--category-dir", required=True)
    p.add_argument("--kb-dir", required=True, help="用于在 _meta/taxonomy.md 里定位 category-dir 对应的说明/备注")
    p.set_defaults(func=cmd_list_targets)

    p = sub.add_parser("retarget", help="挪动已归档页面后，同步更新manifest里的targets")
    p.add_argument("--kb-dir", required=True)
    p.add_argument("--source", required=True, help="要更新的源文件路径，需是manifest里已存在的key")
    p.add_argument("--target", action="append",
                    help='新的落点路径，可重复传多次，例如 --target "01-a.md" --target "02-b.md"')
    p.set_defaults(func=cmd_retarget)

    p = sub.add_parser("create-page", help="light 模式：LLM 定分类决策，脚本创建页面文件（复制正文+自动生成 OKF front-matter）")
    p.add_argument("--kb-dir", required=True)
    p.add_argument("--source", required=True, help="源 md 文件路径")
    p.add_argument("--target", required=True, help="目标页面路径（相对于 kb-dir），例如 01-产品文档/产品A/功能概述.md")
    p.add_argument("--title", required=True, help="页面标题")
    p.add_argument("--type", required=True, help="OKF 概念类型，例如 产品文档、操作手册、架构设计")
    p.add_argument("--description", default="", help="一句话摘要（OKF description 字段）")
    p.add_argument("--tags", default="", help="标签，逗号分隔，例如 产品A,功能,支付")
    p.add_argument("--category", default="", help="分类目录路径，写入 front-matter 的 category 字段")
    p.add_argument("--confidence", default="", choices=["high", "medium", "low"], help="分类置信度")
    p.set_defaults(func=cmd_create_page)

    p = sub.add_parser("quick-classify", help="light 模式：提取源文件标题/headings/首段，输出 JSON 供 LLM 做分类决策（不读全文）")
    p.add_argument("--source", required=True, help="源 md 文件路径")
    p.add_argument("--max-lines", type=int, default=15, help="首段最多提取多少行（默认 15）")
    p.set_defaults(func=cmd_quick_classify)

    p = sub.add_parser("merge-append", help="light 模式合并：把源文件正文追加到已有知识库页面末尾，自动更新 sources")
    p.add_argument("--kb-dir", required=True)
    p.add_argument("--source", required=True, help="源 md 文件路径")
    p.add_argument("--target", required=True, help="目标页面路径（相对于 kb-dir），必须是已有页面")
    p.add_argument("--label", default="", help="合并小节标题（默认用源文件名）")
    p.set_defaults(func=cmd_merge_append)

    p = sub.add_parser("gen-index", help="为整棵知识库树的每一层生成/刷新 index.md（OKF风格的目录清单）")
    p.add_argument("--kb-dir", required=True)
    p.set_defaults(func=cmd_gen_index)

    p = sub.add_parser("log-entry", help="往知识库根目录的 log.md 追加本轮运行的变更记录（OKF风格的可读变更历史）")
    p.add_argument("--kb-dir", required=True)
    p.add_argument("--entry", action="append",
                    help='一条变更记录，可重复传多次，例如 --entry "**Create**: 新建页面 xxx.md"')
    p.set_defaults(func=cmd_log_entry)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
