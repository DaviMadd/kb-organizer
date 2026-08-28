# kb-navigator

在 [kb-organizer](../kb-organizer/) 构建的知识库中高效检索和浏览内容。

## 为什么需要这个？

kb-organizer 负责**构建**知识库（分类、合并、增量更新），但知识库建好之后，当 AI Agent 需要**查询**其中的信息来回答用户问题时，怎么高效定位？

kb-navigator 就是干这个的——渐进式检索，不盲目全量扫描。

## 检索策略

```
读根 index.md → 定位分类目录
  → 读分类 index.md → 筛选候选页面
    → kb-read 预览骨架 → 判断是否值得深读
      → 只读命中页面的正文
```

默认路径只需读 **3-5 个文件**就能定位目标页面。

## 命令

```bash
# 全文元数据检索（备选路径，跨分类搜索时用）
python3 scripts/kb_navigator.py kb-search --kb-dir ./my-kb \
  --query "支付网关 故障处理" --limit 5

# 页面结构预览（看 headings + 首段，不读全文）
python3 scripts/kb_navigator.py kb-read --page ./my-kb/02-运维手册/支付网关运维手册.md
```

## 前置条件

- 知识库已由 kb-organizer 构建完成
- 知识库包含 `index.md`（每层目录清单）和 OKF 标准 front-matter

## 项目结构

```
kb-navigator/
├── SKILL.md                    # Skill 流程定义（LLM 读这个）
├── scripts/
│   └── kb_navigator.py         # 检索工具（kb-search + kb-read）
└── README.md                   # 本文件
```

## 与 kb-organizer 的关系

| | kb-organizer | kb-navigator |
|---|---|---|
| 职责 | 构建知识库 | 检索知识库 |
| 操作 | 写入（创建/合并/分类） | 读取（导航/预览/提取） |
| 使用频率 | 定期运行 | 按需查询 |

两者完全独立，可以单独部署。90% 的使用场景只需要 kb-navigator。
