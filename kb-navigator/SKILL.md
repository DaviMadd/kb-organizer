---
name: kb-navigator
description: 在已有的 kb-organizer 知识库中检索和浏览内容。当用户向 Agent 提问专业领域问题、Agent 需要查询知识库中的信息时，用这个 Skill 渐进式定位相关内容——先读 index.md 逐层钻取，再用 kb-read 预览骨架，最后只读命中页面的正文。不需要加载 kb-organizer 的构建能力。当用户提到"查一下知识库""在知识库里找""帮我查XX的资料""知识库里有没有关于XX的内容"，或者需要从一个已有的知识库中检索信息来回答问题，都适用这个 skill。
---

# kb-navigator

> 在 kb-organizer 构建的知识库中高效导航和检索内容。

## 解决什么问题

知识库已经建好了，但当 Agent 需要回答专业问题时，怎么快速定位到相关页面，
而不是逐文件盲目读取？本 Skill 定义了渐进式检索流程：
利用每层 index.md 的目录结构逐层缩小范围，最终只读命中页面的正文。

## 前置条件

- 知识库已由 `kb-organizer` 构建完成（有 index.md、taxonomy.md、front-matter）
- `kb_navigator.py` 脚本可用（位于本 Skill 的 `scripts/kb_navigator.py`）

## 核心原则

1. **先导航，后搜索。** 默认走 index.md 逐层钻取（R-Step 1 → 2），只在跨分类或无法定位时才用 `kb-search` 做全文元数据检索。
2. **先看骨架，后读正文。** 用 `kb-read` 提取 headings + 首段判断相关性，不要一上来就读全文。
3. **只读必要的文件。** 整个检索过程中，读取正文的页面不超过 5 篇。

## 脚本命令

本 Skill 使用 `scripts/kb_navigator.py`，包含两个子命令：

- **`kb-search`** — 全文元数据检索（备选路径）。扫描所有页面的 front-matter，按关键词匹配打分，返回候选列表。不读正文。
- **`kb-read`** — 页面结构预览。提取一个页面的 front-matter + headings + 首段，不返回正文全文。

## 检索流程

### R-Step 1 — 读根 index.md，定位分类

读 `<kb-dir>/index.md`（1 个文件），看到所有顶级分类目录及其描述。
根据用户问题判断该去哪个分类目录找。

例如看到：
```
* [01-产品文档/](01-产品文档/index.md) - 说明：接口文档、功能规格、需求文档。
* [02-运维手册/](02-运维手册/index.md) - 说明：运维操作、故障处理、巡检手册。
```
用户问"支付网关故障处理" → 去 `02-运维手册/`。

### R-Step 2 — 读分类 index.md，筛选候选页面

读 `<kb-dir>/02-运维手册/index.md`（1 个文件），看到该目录下所有页面及 description：
```
* [支付网关运维手册](支付网关运维手册.md) - 支付网关日常巡检与故障处理
* [数据库变更规范](数据库变更规范.md) - 生产环境DDL变更流程
```
根据 description 筛选候选页面。如果该目录还有子目录，继续往下读一层 index.md。

**如果问题跨多个分类或无法从 index.md 定位**：跳到 R-Step 2b 用 `kb-search`。

### R-Step 2b — 全文元数据检索（备选）

当 index.md 逐层钻取不够用时（跨分类、无法映射、候选太多），调 `kb-search` 做全文 front-matter 检索：

```bash
python3 scripts/kb_navigator.py kb-search --kb-dir <kb-dir> \
  --query "支付网关 故障处理" --limit 5
```

脚本扫全部页面的 front-matter（不读正文），返回按相关性打分的候选列表。

支持的过滤参数：
- `--type "运维手册"` — 精确匹配文档类型
- `--tags "支付网关,运维"` — 标签匹配（任一命中即可）
- `--category "02-运维手册"` — 限定搜索范围到某个分类目录

### R-Step 3 — 结构预览（判断是否值得深读）

对候选页面调 `kb-read` 看骨架：

```bash
python3 scripts/kb_navigator.py kb-read --page <kb-dir>/02-运维手册/支付网关运维手册.md
```

返回 headings + 首段 + sources 列表。LLM 据此判断：
- headings 里有没有与问题直接相关的章节？
- 首段内容是否印证了 description 的判断？
- 如果不相关，回到 R-Step 2 看其他候选，或回 R-Step 1 换分类

### R-Step 4 — 读取命中页面正文

经过 R-Step 2/3 的筛选，通常只剩 1-3 篇页面值得读全文。
此时才用 Read 工具读取页面正文，提取答案。

**效率约束**：整个检索过程中，读取正文的页面不超过 5 篇。
如果 5 篇还不够，说明知识库的分类粒度可能太粗，建议用户考虑拆分。

### R-Step 5 — 回答并标注来源

回答用户问题时标注信息来源（哪篇页面、哪个章节），方便用户回溯验证。
如果知识库中没有找到相关内容，如实告知，不要编造——知识库没有的不代表不存在，只是这里没收录。

## 效率保障

| 阶段 | 读取范围 | 文件数 |
|------|---------|--------|
| R-Step 1 读根 index.md | 目录清单 | 1 |
| R-Step 2 读分类 index.md | 页面清单 | 1-2 |
| R-Step 2b（备选）kb-search | 只读 front-matter | 全部页面（但只解析头部） |
| R-Step 3 kb-read | headings + 首段 | 候选 top 3-5 篇 |
| R-Step 4 Read | 正文全文 | 命中 1-3 篇 |

**默认路径（R-Step 1 → 2 → 3 → 4）只需读 3-5 个文件就能定位到目标页面。**
