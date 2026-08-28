#!/usr/bin/env python3
"""
kb_navigator.py - kb-navigator skill 的辅助工具

独立于 kb-organizer 的检索脚本，只依赖知识库的已有结构
（index.md / front-matter / taxonomy.md），不修改任何知识库文件。

子命令:
  kb-search   扫描全部页面 front-matter，按关键词匹配打分，返回候选列表（不读正文）。
              备选路径——默认应走 index.md 逐层钻取。
  kb-read     提取页面骨架（front-matter + headings + 首段），不返回正文全文，
              供 LLM 判断是否值得深读。
"""
import argparse
import json
import sys
from pathlib import Path

RESERVED_FILENAMES = {"index.md", "log.md"}


def _parse_front_matter(text: str) -> dict:
    """从 markdown 文件开头提取 front-matter 键值对。"""
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
    """从 markdown 文件中提取正文（去掉 front-matter）。没有 front-matter 则返回原文。"""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    body_start = end + 4
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    return text[body_start:]


def _parse_tags(raw: str) -> list:
    """从 front-matter 的 tags 字段解析出标签列表。支持 '[a, b, c]' 和 'a, b, c'。"""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [t.strip() for t in raw.split(",") if t.strip()] if raw else []


def cmd_kb_search(args):
    """扫描知识库所有页面的 front-matter，按关键词匹配打分，返回候选列表。
    不读任何页面正文。这是备选路径——默认应走 index.md 逐层钻取。
    """
    kb = Path(args.kb_dir).resolve()
    if not kb.exists():
        print(f"❌ 知识库目录不存在: {kb}", file=sys.stderr)
        sys.exit(1)

    query_terms = []
    if args.query:
        query_terms = [t.strip() for t in args.query.split() if t.strip()]
    filter_type = args.type or ""
    filter_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    filter_category = args.category or ""
    limit = args.limit

    search_dir = kb
    if filter_category:
        search_dir = kb / filter_category
        if not search_dir.exists():
            print(json.dumps({
                "query": args.query or "",
                "total_pages_scanned": 0,
                "results": [],
                "error": f"分类目录不存在: {filter_category}",
            }, ensure_ascii=False, indent=2))
            return

    results = []
    total_scanned = 0

    for p in sorted(search_dir.rglob("*.md")):
        rel = str(p.relative_to(kb))
        # 跳过元数据目录
        if any(part.startswith("_") for part in Path(rel).parts):
            continue
        if p.name in RESERVED_FILENAMES:
            continue

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        fm = _parse_front_matter(text)
        if not fm:
            continue

        total_scanned += 1
        title = fm.get("title", "")
        desc = fm.get("description", "")
        doc_type = fm.get("type", "")
        tags = _parse_tags(fm.get("tags", ""))

        score = 0

        # type 精确匹配
        if filter_type and doc_type == filter_type:
            score += 3

        # tags 匹配
        for ft in filter_tags:
            if ft in tags:
                score += 10
        for qt in query_terms:
            for tag in tags:
                if qt in tag or tag in qt:
                    score += 10
                    break

        # title 关键词匹配
        for qt in query_terms:
            if qt in title:
                score += 5

        # description 关键词匹配
        for qt in query_terms:
            if qt in desc:
                score += 2

        # 没有任何匹配就跳过（除非没有任何过滤条件）
        if score == 0 and (query_terms or filter_tags or filter_type):
            continue

        results.append({
            "path": rel,
            "title": title,
            "type": doc_type,
            "description": desc,
            "tags": tags,
            "score": score,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:limit]

    print(json.dumps({
        "query": args.query or "",
        "total_pages_scanned": total_scanned,
        "results": results,
    }, ensure_ascii=False, indent=2))


def cmd_kb_read(args):
    """提取一个页面的"骨架"——front-matter 全字段 + headings + 首段。
    不返回正文全文，供 LLM 判断是否值得深读。
    """
    page_path = Path(args.page)
    if not page_path.exists():
        print(f"❌ 页面不存在: {page_path}", file=sys.stderr)
        sys.exit(1)

    text = page_path.read_text(encoding="utf-8", errors="ignore")
    fm = _parse_front_matter(text)
    body = _extract_body(text)
    lines = body.splitlines()
    total_lines = len(lines)
    max_lines = args.max_lines

    # 提取 headings
    headings = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped)

    # 提取首段（标题后的第一个非空段落）
    first_paragraph_lines = []
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
            continue
        if found_heading and stripped != "":
            in_first_para = True
        if in_first_para:
            if stripped == "":
                break
            if len(first_paragraph_lines) < max_lines:
                first_paragraph_lines.append(line)

    # 提取 source_files（从 front-matter 的 sources 字段）
    source_files = []
    if "sources:" in text:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- id:"):
                source_id = stripped[5:].strip()
                if source_id:
                    source_files.append(source_id)

    result = {
        "path": str(page_path),
        "front_matter": fm,
        "headings": headings[:30],
        "first_paragraph": "\n".join(first_paragraph_lines[:max_lines]),
        "total_lines": total_lines,
        "source_files": source_files,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="kb-navigator 知识库检索工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("kb-search",
                       help="扫描全部页面 front-matter 做关键词匹配打分，返回候选列表（不读正文）")
    p.add_argument("--kb-dir", required=True, help="知识库目录路径")
    p.add_argument("--query", default="", help="空格分隔的关键词，在 title/description/tags/type 中匹配")
    p.add_argument("--type", default="", help="精确匹配 front-matter 的 type 字段")
    p.add_argument("--tags", default="", help="逗号分隔的标签，任一匹配即命中")
    p.add_argument("--category", default="", help="限定在某个分类目录下搜索（相对于 kb-dir）")
    p.add_argument("--limit", type=int, default=10, help="最多返回几条（默认 10）")
    p.set_defaults(func=cmd_kb_search)

    p = sub.add_parser("kb-read",
                       help="提取页面骨架（front-matter + headings + 首段），不返回正文全文")
    p.add_argument("--page", required=True, help="页面路径（绝对路径或相对于 kb-dir）")
    p.add_argument("--max-lines", type=int, default=15, help="首段最多提取多少行（默认 15）")
    p.set_defaults(func=cmd_kb_read)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
