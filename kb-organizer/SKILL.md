---
name: kb-organizer
description: 把一批已经转换好的 Markdown 文档（通常来自 doc/xls/ppt 转换工具）分类整理进一个有层级结构的知识库（一棵可浏览的分类 md 文件树，不是 RAG 向量库），判断每篇文档该合并进已有页面还是新建页面，遇到分类不明确或内容矛盾时显式标注交给人工确认而不是硬塞或悄悄覆盖。每次运行都基于文件哈希对比，只处理新增和变更的文档，支持增量更新、可中断可恢复。当用户提到要把一堆 md/markdown 文档"分类整理""归纳整理成知识库""建wiki""合并到知识库""增量更新知识库"，或者给了一批转换好的 md 文件要求组织归档、按主题分类，都应该用这个 skill——即使用户没有明确说"skill"或"知识库"这两个词，只要是把一堆笔记/文档按主题整理进目录结构，都适用。
---

# kb-organizer

> **v6** — 版本历史见 `CHANGELOG.md`（skill 工具本身的演进记录，不是某个知识库实例的 `log.md`，两者别搞混）。

## 解决什么问题

维护一棵可浏览的分类 md 文件树，页面是消化过的知识，不是原始转换稿的复印。支持增量：同一源目录反复跑，只处理变化过的文件，中途中断也不破坏已整理的结构。

## 不适合的场景

- 只是要把 doc/xls/ppt 转成 md——这个 skill 假设输入已经是 md 了。
- 要搭 RAG/向量检索问答——本 skill 产出的分类 md 可以被检索系统消费，但不做 embedding。
- 只有几篇文档、用户只是想让你读了直接回答问题——直接读，不用走流程。

## 核心原则

1. **能用代码做的事不要靠推理去做。** hash 对比、清单登记、front-matter 抽取交给 `scripts/kb_tools.py`；分类判断、合并、识别冲突交给你自己的理解力。
2. **写入动作要可追溯、可撤销。** 页面 front-matter 记录来源文件和 hash；冲突显式标注在正文里，不能用新信息悄悄覆盖旧信息。
3. **目录增长要有人把关，但该拆的时候不能装看不见。** 新建一级分类或往下再拆一层，都要走"先提出来、按 `interaction_mode` 决定是等确认还是自动执行"的流程（细节见 Step 4），不因为层级已经比较深就放松标准。执行拆分必须**对称**——涉及这个维度的所有旧文件要和新文件一起挪，不能只给新内容建目录、把旧文件晾在原地。目录深度一般不超过 3~4 级，超过通常说明该拆的是"单篇页面太长"，不是"目录不够细"。
4. **增量更新靠 hash，不靠记忆。** 每次先跑 `scan`，让脚本告诉你什么变了。
5. **处理深度不是默认拉满的选项。** 分类判断（读文件、定分类、写摘要）每篇都做；深度提炼重组只在 `processing_mode` 要求或确有必要时才做，默认轻量。详见 Step 3。

## 目录结构

```
kb/
├── index.md               # 本层目录清单，脚本自动生成/刷新（Step 6）
├── log.md                 # 变更历史，人类可读（Step 6）
├── _meta/
│   ├── manifest.json      # 源文件 -> 落点 登记表，脚本维护，不要手工改
│   ├── taxonomy.md        # 分类目录及说明，需人工确认过
│   └── config.json        # 交互/处理策略偏好，脚本维护（Step 0）
├── _inbox/                 # 分类不明确/低置信度内容暂存处
├── 01-产品文档/
│   ├── index.md
│   └── 产品A/功能概述.md
└── ...
```

`index.md`/`log.md`/`config.json` 是保留文件名，源文档不能被分类成这几个名字——遇到这种命名冲突（概率很低），换个更具体的标题再落位。

## 运行流程

### Step 0 — 确认路径，读取或设置运行偏好

不清楚源 md 目录和 kb-dir 在哪就先问用户。检查 `<kb-dir>/_meta/manifest.json`：不存在 → 首次运行，执行 `init`；存在 → 增量运行。

不管首次还是增量，都先读一次偏好：

```bash
python3 scripts/kb_tools.py get-config --kb-dir <kb-dir>
```

- `found: false`（首次运行，或从没有 config 机制的旧版本知识库继续跑）→ 用交互式选项问用户两个问题，然后 `set-config` 保存，后续运行自动复用：
  1. **交互模式**：每一步都确认，还是自动执行、不用一步步确认（静默）？
  2. **处理策略**：skill 自动判断轻量/深度（推荐），还是强制全轻量，还是强制全深度？
- `found: true` → 直接按 `interaction_mode`/`processing_mode` 执行，跟用户说一句"沿用之前设置：XX/XX"就行，不用重新问。用户在对话里明确要求换模式时，当场 `set-config` 更新。

```bash
python3 scripts/kb_tools.py set-config --kb-dir <kb-dir> \
  --interaction-mode interactive|silent \
  --processing-mode smart|light|deep
```

`processing_mode` 怎么影响 Step 3/4，`interaction_mode` 怎么影响 Step 4 的"要不要停下来问"，见对应步骤。

### Step 1 — 扫描变更（永远先跑，不要跳过）

```bash
python3 scripts/kb_tools.py scan --source <源md目录> --kb-dir <kb-dir>
```

输出 `new`/`changed`/`unchanged`/`deleted`。`deleted` 不要自动删对应知识库页面（可能已被合并进其他页面，删源文件不代表知识作废），列出来提示用户手动确认。

只处理 `new`/`changed`。文件多（几十上百篇）就分批：处理一批、写一次报告、问要不要继续，不要试图一次性塞进同一轮对话。

### Step 2 — 分类目录（taxonomy）

**首次运行：** 读源目录里文件的标题和前几段，归纳一版两级分类草案，一级分类 6~12 个。`references/frontmatter-and-taxonomy.md` 有行业参考起点，按实际内容调整、不要照抄。

某个分类下已经能看出潜在细分维度（系统名/产品名等）但数量还不够拆时，在 `taxonomy.md` 对应分类下留一句备注（例如"当前只有 fins 系统内容，未来出现其他系统同类文档时按系统名拆子目录"）。这句备注会在 Step 4 调用 `list-targets` 时被自动带出来，不需要另外记得查——前提是标题层级按模板约定写（`##` 一级、`###` 二级……），层级错了脚本匹配不到。这个模式可能在子目录里重复出现，识别到就照样留备注。

写完草案连同备注写进 `_meta/taxonomy.md`，**给用户看一眼、等确认或修改再继续**——这步跑错后面全跑歪。

**增量运行：** 直接读 `_meta/taxonomy.md` 当分类菜单。文档明显不属于任何现有分类时不要自己加一级分类，放 `_inbox/`，报告里列出来并给建议，交给用户决定。

### Step 3 — 分类判断（每篇都做）+ 深度提炼（按条件触发）

**分类判断，不管什么模式都要做**：读全文，判断文档类型、拟标题、写一句摘要（可以直接摘原文第一句或小标题，不用精心组织）、判断归入 taxonomy 哪个分类、给自己一个置信度判断。这是分类的最低限度信息，省不掉。

**深度提炼**（挑值得沉淀的内容、去转换噪音、重组表达）——按 `processing_mode` 触发：

- `deep`：每篇都做。
- `light`：都不做，即便要合并（合并方式见 Step 4 的"轻量合并"）。
- `smart`（默认）：满足其一才做——这篇要合并进已有页面（需要综合才有意义，不是简单拼接）；或原文有明显转换噪音（页眉页脚、导航栏残留、大段重复模板文字）。其余按轻量处理。

**不管什么模式，读到内容矛盾都要标注**（见 `references/merge-and-conflict-conventions.md`）——这是安全机制，不受处理深度设置影响。

### Step 4 — 落位决策：合并 / 新建 / 子目录拆分 / inbox

按 taxonomy 和已有结构确定候选目录（任意深度都适用），查询：

```bash
python3 scripts/kb_tools.py list-targets --kb-dir <kb-dir> --category-dir <kb-dir>/<候选目录>
```

返回已有页面清单（含 front-matter）和自动匹配的 `taxonomy_note`。据此判断两件事：

1. 有没有主题重合的候选页面？
2. 已有内容加上这篇，是不是已经能按某个维度（系统名/产品名/模块名）分成两拨了？参考 `taxonomy_note`，判断依据和执行要求见原则 3。

**触发第2问（识别出新维度）** → 按 `interaction_mode` 分流：
- `interactive`：先不建任何新目录，新文档放进候选目录本身；把检测到的情况告诉用户（"`01-系统架构` 下检测到 fins 系统和 a系统 两类内容，建议拆出子目录 `01-fins系统`、`02-a系统`，需要挪动 N 个文件"），**结束这一轮回复，等用户明确回复再继续处理后面排队的文件**。
- `silent`：按建议直接对称执行（不暂停），但要在 Step 6 的 log.md 里用 `**Restructure（静默自动执行，请核对）**` 这样的标签显著标注，最终报告里也要提一句。

执行细节（对称挪动、`retarget`、taxonomy 备注更新）见 `references/frontmatter-and-taxonomy.md`。

**候选页面主题重合** → 合并，按 Step 3 判定的处理深度分两种写法：
- **深度**：打开候选页面全文，综合改写，front-matter `sources` 追加来源；矛盾内容显式标注（见 `references/merge-and-conflict-conventions.md`）。
- **轻量**：不改写已有内容，在文末追加 `## 来自 <源文件名>（合并于<日期>）` 小节，新内容基本原样放入；`sources` 照样要追加。**矛盾内容不管深浅都要标注**。

**没有合适候选页面，分类明确** → 新建页面，front-matter 按 `references/frontmatter-and-taxonomy.md` 模板；轻量模式下摘要直接摘原文即可。

**分类不明确/低置信度** → `_inbox/`，front-matter 写清楚"待归类"和判断依据。

挪动已归档页面后同步 manifest（只改 targets，不动 hash/status）：

```bash
python3 scripts/kb_tools.py retarget --kb-dir <kb-dir> \
  --source "<原始源文件相对路径>" \
  --target "01-系统架构/01-fins系统/fins收报模块理解文档.md"
```

一个源文件落多个页面就重复传 `--target`。

### Step 5 — 登记 manifest（每篇处理完立刻登记）

```bash
python3 scripts/kb_tools.py update-manifest \
  --kb-dir <kb-dir> --source "<scan输出里的相对路径>" --hash "<scan输出里的hash>" \
  --status merged|new_file|inbox --target "01-产品文档/产品A/功能概述.md" \
  --title "..." --doc-type "产品文档"
```

一篇文档落多个页面就重复传 `--target`（不要拼 JSON 字符串塞给某个参数——单引号包 JSON 双引号在 Windows cmd/PowerShell 下容易解析失败）。每处理完一篇立刻登记，不要攒到最后：中途中断，下次重跑 `scan` 时已处理的文件会判定为 `unchanged`，不会重复劳动。

`deleted` 列表里用户确认要清理的，用 `remove-entry` 删记录（不会自动删知识库页面）。

### Step 6 — 刷新 index.md，写 log.md（整批处理完做一次，不用每篇都做）

参考 Google 的 Open Knowledge Format（OKF）约定，让知识库不依赖本 skill 也能被浏览。OKF 的核心字段约定：

- **概念页面 front-matter**：`type`（必填，如"产品文档""操作手册"）、`title`、`description`（一句话摘要，OKF 用这个字段名，不是 summary）、`tags`、`resource`（可选，指向外部资产的 URI）。`gen-index` 读这些字段来生成目录条目。
- **index.md**：每层列出子目录和本层页面，每条展示 `type`、`title`、`description`、`tags`，格式如 `* [标题](路径) — \`类型\` · 描述 · tags: 标签列表`。根目录 index.md 可带 `okf_version` front-matter。
- **log.md**：按日期分组的叙事变更历史，最新在最上，日期用 ISO 8601 `YYYY-MM-DD` 格式。

```bash
python3 scripts/kb_tools.py gen-index --kb-dir <kb-dir>
```

```bash
python3 scripts/kb_tools.py log-entry --kb-dir <kb-dir> \
  --entry "**Ingest**: 处理 12 篇源文档（3 篇新增、2 篇变更，7 篇跳过）" \
  --entry "**Create**: 新建页面 02-设计模板/防重设计模板.md" \
  --entry "**Restructure**: 01-系统架构 拆出子目录 01-fins系统、02-a系统"
```

挑对用户有意义的事件写，不是每篇文档一条流水账。`silent` 模式下自动执行的结构性调整（Step 4）要用 `**Restructure（静默自动执行，请核对）**` 这类带标注的标签，方便日后一眼找到"哪些是模型自己决定的"。`log.md` 是给人看的叙事，`manifest.json` 是给 `scan` 比对哈希用的机器数据，两者不互相替代，Step 5 该登记还是要登记。

### Step 7 — 运行报告

给用户一个简短总结：

- 处理/跳过/deleted 各几篇
- 新建、合并了哪些页面
- 冲突标注的页面（最需要人看）
- 触发过的子目录拆分建议——`interactive` 下已问过/待用户回复的，`silent` 下已自动执行、需要核对的，都要提
- inbox 新增了什么、建议怎么处理

不需要长篇大论，重点是"有没有需要人判断的地方"。

## 大批量存量文档

- 先用 10~20 篇代表性文档跑一遍完整流程，taxonomy 和合并效果定下来再批量跑
- 按批次分段，每段走完 Step 5 再进下一段，保证可中断可恢复
- Step 6 按批次做一次就够，`gen-index` 全量重生成，频繁调用没有额外收益
- inbox 堆多了单独花一轮处理，不跟正常流程混

## 参考文件

- `references/frontmatter-and-taxonomy.md` —— front-matter 字段规范、taxonomy.md 格式、行业分类参考、目录深度经验值、挪动已归档页面的执行清单
- `references/merge-and-conflict-conventions.md` —— 深度/轻量两种合并写法、冲突标注写法、哪些情况必须转人工
