# kb-organizer 版本历史

记录这个 skill **工具本身**的变化（不是某个具体知识库实例的内容变化——那个记在
每个知识库自己的 `log.md` 里，见 SKILL.md Step 6）。每次改动 SKILL.md 或
`scripts/kb_tools.py` 的行为，都在这里加一条，说明改了什么、为什么改。

## v7 — 2026-08-20

**对齐 OKF（Google Open Knowledge Format）标准字段，`gen-index` 生成的目录条目从只展示 title + summary 改为展示完整的 OKF 结构化字段。**

- `gen-index` 现在从页面 front-matter 读取 `type`、`description`、`tags`、时间戳，
  生成的 index 条目格式改为 `* [标题](路径) — \`类型\` · 描述 · tags: 标签 · updated: 时间戳`，
  和 OKF §8 的 progressive disclosure 约定一致。
- front-matter 摘要字段从 `summary` 改为 OKF 标准的 `description`，`list-targets`
  返回结果同步对齐，新增返回 `type` 字段。
- 新增 `_extract_timestamp` 辅助函数：兼容 OKF v0.2 的 `generated: { by, at }` 格式
  和旧式 `timestamp` 字段，优先取 `generated.at`。
- `references/frontmatter-and-taxonomy.md` 模板加了 `type`（必填）字段，`summary` →
  `description`，字段说明标注了对齐 OKF。
- SKILL.md Step 6 补充了 OKF 核心字段约定的明确说明（`type` 必填、`description` 不是
  `summary`、index 条目格式、根目录 `okf_version` 等）。

## v6 — 2026-08-20

**加入运行偏好配置（交互/静默、处理深度分级），并给 SKILL.md 大幅瘦身。**

- 新增 `get-config`/`set-config` 子命令，写入 `_meta/config.json`：`interaction_mode`
  （`interactive`/`silent`）和 `processing_mode`（`smart`/`light`/`deep`）。首次运行
  （或从没有这套机制的旧知识库继续跑）时通过交互式选项问一次，后续运行自动复用，
  不用每次都问；用户随时可以在对话里要求切换，当场 `set-config` 更新。
- Step 3 拆成两段：**分类判断**（读文件、定分类、写摘要）不管什么模式都要做，是
  分类的最低限度信息，省不掉；**深度提炼**（挑内容、去噪音、重组表达）只在
  `processing_mode: deep`，或 `smart` 模式下确有必要（要合并、原文噪音明显）时才做，
  之前版本不分场景一律要求深度提炼，对"单一来源、原文本身干净"这种最常见的情况是
  浪费算力。
- Step 4 合并分支相应拆成"深度合并"（综合改写，沿用之前的补充/更新/冲突三分法）
  和"轻量合并"（追加式，不改写已有内容，按来源分块原样放入）——**不管哪种，读到
  内容矛盾都必须显式标注**，这条不受处理深度影响，是安全机制不是质量增强项。
- Step 4 的子目录拆分确认流程按 `interaction_mode` 分流：`interactive` 沿用原来的
  "先不建目录、告诉用户、停下来等回复"；`silent` 改为直接按建议对称执行，但要在
  `log.md` 里用 `**Restructure（静默自动执行，请核对）**` 这样带标注的标签记录，
  方便日后一眼找到哪些是模型自己决定的。
- SKILL.md 整体瘦身：去掉了大量"当年为什么这么改"的背景叙事（这些案例现在都在本
  changelog 里，不需要在正文重复论证）、把同一条规则在多处重申的情况合并成只讲
  一次、大量口语化的括注说明改成更紧的祈使句。粗略估算正文 token 量从约 9100 降到
  约 5200，减了四成多，执行规则本身没有删减。
- `references/frontmatter-and-taxonomy.md`、`references/merge-and-conflict-conventions.md`
  同步更新：前者补充"挪动页面时'要不要做'由 interaction_mode 决定、'怎么做'看这
  份清单"的分工说明；后者新增"轻量合并"一节，并把"必须转人工"清单里跟目录结构
  相关的条目改成"必须显式处理（等确认或自动执行+标注），不能悄悄跳过"，因为静默
  模式下这类调整不再是无条件转人工了。

## v5 — 2026-08-20

**加入 OKF 风格的 `index.md` / `log.md`，并开始做版本管理。**

- 新增 `gen-index` 子命令：为知识库树每一层生成/刷新 `index.md`，列出子目录和本层
  页面各带一句话说明，参考 Google Open Knowledge Format 的 progressive disclosure
  约定。全量重新生成，自底向上遍历，只有真正有内容的目录才会被列进父级的"子目录"
  清单，避免指向空目录的死链接。
- 新增 `log-entry` 子命令：往知识库根目录的 `log.md` 追加人类可读的变更记录，按
  日期分组、最新的在最上面，同一天多次运行自动追加到当天标题下。和 `manifest.json`
  分工不同——一个是给人看的叙事历史，一个是给脚本比对哈希用的机器数据。
- `list-targets` 现在会排除 `index.md` / `log.md`，不会把这两个保留文件误当成
  知识页面列进候选合并列表。
- 运行流程新增 Step 6（刷新 index/写 log），原 Step 6"运行报告"顺延为 Step 7，
  并且现在要求运行报告直接复用 `log.md` 写的内容，不用另外组织一套说法。
- 本文件（`CHANGELOG.md`）从这个版本开始存在，v1~v4 是回溯补充的历史记录。

## v4 — 2026-08-19

**修复"该拆子目录时执行不完整"的问题：只给新内容建了子目录、旧文件却留在原地不动。**

- `list-targets` 现在强制要求同时传 `--kb-dir`，自动按标题层级去 `taxonomy.md`
  匹配候选目录对应的说明/备注一起返回——之前"要不要回去检查备注"完全靠模型自觉，
  实测经常被漏掉，即使备注写对了，增量运行时也不一定会被翻出来看。
- 修了 `find_taxonomy_note` 的一个匹配 bug：原来的边界判断条件会被文档最外层的
  H1 标题直接触发，导致连一级分类都匹配不到。
- Step 4 改写：明确禁止在用户确认前新建任何子目录（哪怕只是为新文档建一个）；
  检测到需要拆分维度时必须真正结束这一轮回复、等用户明确回复了再继续处理后面
  排队的文件，不能自己心里"记下"然后接着往下处理；一旦确认要拆，必须是**对称
  执行**——识别出的维度涉及的所有旧文件都要跟着新文件一起挪，不能挪一半。
- 要求执行完重组后，`taxonomy.md` 里更新的备注必须描述这次实际执行的拆分依据，
  不能写成一个不相关的、结构上对不上的未来触发条件。

## v3 — 2026-08-18

**修复 Windows 下 CLI 参数解析崩溃的问题。**

- `update-manifest` / `retarget` 的落点参数从"要求手写一段 JSON 数组字符串"
  （如 `'["a.md","b.md"]'`）改成可重复传的 `--target`（一个落点传一次），因为
  JSON 字符串外面套单引号、里面又是双引号，在 Windows 的 cmd/PowerShell 下经常
  解析失败，模型解决不了只能去手动改 `manifest.json`，风险更大。
- 加了防御性报错：忘记传 `--target` 时给出清楚的中文提示而不是让程序崩溃；
  `manifest.json` 如果被手动改坏（比如多了个逗号），现在会提示具体哪里错、
  建议用 `python3 -m json.tool` 定位，而不是甩一段原生 Python traceback。

## v2 — 2026-08-18

**去掉 git 集成；把"该不该拆子目录"的判断从"只在一级分类下检查一次"泛化成
适用任意层级的通用规则。**

- 删掉了运行流程里的 git 提交步骤——只需要生成到本地文件系统，不对 git 做任何
  假设，`references/merge-and-conflict-conventions.md` 里的 git commit message
  约定也一并删除。
- 原来"新建二级目录需要确认"的规则被泛化：不管候选目录当前是几级，只要涉及
  往下再拆一层，都要走同一套"先提出来、等确认"的流程。
- 加入目录深度上限的建议（一般不超过 3~4 级），超过这个深度通常说明真正该拆的
  是"单篇页面太长该拆成几篇"，不是"目录还不够细"。

## v1 — 2026-08-17

**首个版本。**

- 基本流程：扫描变更（基于 hash 对比、支持增量）→ 首次运行 bootstrap 分类
  目录并要求人工确认 → 逐篇分类抽取 → 落位决策（合并 / 新建 / inbox）→
  登记 manifest（可中断可恢复）→ 运行报告。
- `scripts/kb_tools.py` 提供 `init` / `scan` / `update-manifest` / `remove-entry`
  / `list-targets` 几个确定性辅助命令，哈希对比、清单维护这类事交给脚本，
  分类判断、合并、冲突识别这类事交给模型。
- 冲突处理约定：合并时遇到新旧信息矛盾要显式标注，不能悄悄覆盖；front-matter
  的 `sources` 数组记录所有来源文件的路径和 hash，保证可追溯。
