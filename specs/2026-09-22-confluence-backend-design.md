# Design Spec: confluence backend — Atlassian Confluence Cloud 平台后端（acli 为主，MCP 兜底）

- **Date:** 2026-09-22（grill 三轮定稿：传输阶梯为用户裁决修订——acli 不可用且 MCP 可得时用 MCP；其余全按推荐）
- **Status:** draft（design 已逐节过审 + 用户确认；实现未开始；A1 探针 gated）
- **Priority:** medium-high — README 早已把 Confluence 列入联邦后端承诺（README.md:333/351，零代码兑现）；组织工程文档若在 Confluence 则是 query-knowledge 联邦的真实缺口；同时补全「平台后端全走 integration skill」矩阵的第四格
- **ADRs:** 0015（传输：acli 主 / MCP 环境兜底）、0016（内容格式桥：markdown ↔ 最小 storage XHTML）
- **语言:** CONTEXT.md 新增 confluence backend / 传输阶梯 (transport ladder) / 格式桥 (format bridge)；「平台」「后端」「integration skill」「知识空间」「本地后端」条目已同步

## 背景与目标

kgent 平台后端矩阵现有 lark / dingtalk / wecom。新增 **confluence**（Atlassian
Confluence **Cloud**，与三平台同为 SaaS）：`trust_zone: internal` 的一等 backend。
目的（用户确认）：

1. query-knowledge 联邦补上 Confluence 内容（工程/内部空间），带原生 Atlassian URL 引用
2. 完整读写对等：search / read / **write（create/update/delete）** / undo——与其他
   平台后端同一纪律（route → journal begin → 写 → journal end → 读回校验）
3. real-tenant e2e 的第四个目标（仅 confluence 腿变更时运行，专用 sandbox 空间 +
   事后 stray 清扫——2026-09-11 维护者裁决不变）

## 决策摘要

- **命名与归属**：平台后端（非 local- 家族）：config 名 `confluence`、skill
  `confluence-integration`、URI `kgent://confluence/<page-id>`（数字 page id，
  标题改名与空间移动不破坏引用）；trust_zone `internal`。
- **执行层与传输阶梯**（ADR 0015）：一切操作经 `confluence-integration` skill。
  传输按环境一次性裁决：官方 `acli`（主）→ Atlassian Remote MCP（`acli` 缺失且
  MCP 可检测时）→ 优雅禁用。`kgent setup` 探测报告，skill Gate 逐次复核。adapter
  只走 acli 路径；MCP 只在 skill 层。不新增 transport config 键——有效传输是
  环境事实（`acli` / `mcp` / `unavailable` 三值报告）。
- **adapter 车道**（dingtalk/wecom 先例 + lark wiki 先例）：`ConfluenceAdapter`
  只声明 **document_search + read + wiki capability**（spaces list/create、page
  node create）；document create/update/delete **不在 adapter**——写车道归
  integration skill（ADR 0004 同规）。archive/unarchive **整个 backend 不支持**
  （Confluence 无页面级 archive API）——capability 缺席声明，skill 已知限制。
- **内容格式桥**（ADR 0016）：markdown ↔ 最小公共子集 storage XHTML（`p`、
  `h1–h6`、`ul/ol/li`、`code/pre`、`table`、`blockquote`、粗斜体、链接）；桥外
  结构读为占位 + fidelity 声明、写不支持即拒绝；转换以 stdlib 实现于
  `kgent formats` CLI，skill 与 adapter 共用，禁止双实现漂移。
- **凭据**：全在传输侧——acli 自有 store（`acli confluence auth login`：site +
  email + API token），MCP 走宿主 OAuth。kgent 零凭据面；doctor 只探测可用性。
- **空间 allowlist**：`backends.confluence.spaces: [<spaceKey>…]`（默认 `[]` =
  已认证用户全部可达空间）；search 的 CQL 与 write 的空间校验都按 allowlist 裁剪；
  allowlist 外的空间不可检索也不可写。
- **undo**：台账机制 `confluence → version-revert`（dingtalk 家族）；补偿 =
  取历史版本正文 → 按当前版本条件重写（Confluence 无原地恢复端点；重写产生新版本，
  历史不丢）；create → 页面移入回收站；delete → 回收站恢复端点。新鲜度单层：
  当前 version == 台账 version_after，否则拒绝（fail closed）——Confluence 是唯一
  权威，无本地副本漂移面，单层检查完备（与 local-fs 双层的差异是本质的，不是偷工）。

config 条目（enable 时）：

```yaml
backends:
  confluence:
    enabled: true
    type: skill            # 恒为 skill；MCP 是 skill 内的工具选择，不是 config type
    skill_name: confluence-integration
    trust_zone: internal
    spaces: []             # allowlist；空 = 全部可达空间
    site: null             # Atlassian 站点 host（如 org.atlassian.net）；native URL 引用用
```

（`site` 键为实现期补遗（2026-09-22）：native URL 引用（N20）需要站点 host，
schema 校验同 `remote`（str|None）。）

## 数据模型映射

| kgent 概念 | Confluence Cloud 对应 | 说明 |
|---|---|---|
| 知识空间 | Space（`spaceId` + `spaceKey`） | `kgent wiki spaces list` 枚举；`--wiki-space` 收 spaceKey |
| 文档 | Page（数字 `pageId`） | `node_type: doc`；URI native id = pageId |
| 父节点 | parent pageId | `parent_node_token`；顶层页面 = 空间根 |
| version | 页面 `version.number`（每次写 +1） | 台账 revision、CAS 字段 |
| 原生 URL | `https://<site>.atlassian.net/wiki/spaces/<spaceKey>/pages/<pageId>/<title-slug>` | slug 缺失时 id-only 形式亦可解析（服务端 301） |
| 检索 | CQL `type=page AND text ~ "<query>"`（+ space 限定） | 仅 keywords 模式；semantics/hybrid 声明不支持 |
| 内容 | storage XHTML ↔ markdown（格式桥） | 正文取 `body.storage`；读转换、写构造 |

v1 明确不做：blog posts、whiteboards、databases、folders（`node_type` 不扩展）、
页面跨空间移动、附件。spaces allowlist 外的页面：search CQL 注入
`space IN ("A","B")`、write 前校验目标 spaceKey，两者都以 allowlist 为准。

## 操作流（confluence-integration skill 承载）

**Gate**：`backends.confluence.enabled` 检查 → 传输阶梯复核（`acli --version`
可执行且 `confluence auth` 有效 → acli；否则宿主 MCP 配置含 Atlassian server 且
工具可达 → mcp；否则优雅禁用并申报 `unavailable`）。凭据永不出现在输出中。

**检索**：acli CQL 搜索（或 MCP `search`）→ 每命中映射 `SearchResult`：
`kgent://confluence/<pageId>` URI + 空间/标题/摘要 + `native_url`；CQL 查询串
必须转义（Lucene 特殊字符 `"+-&|!(){}[]^~*?:\/`）——转义是负向约束，有专属测试。
top_k → `limit`。

**读取**：按 pageId 取页面（version + `body.storage`）→ 格式桥转 markdown →
返回正文 + 元数据。读不落台账。

**写入**（create/update/delete 同一纪律；ADR 0004：写经 skill）：

```
kgent route --dry-run             # 只读裁决（confluence: internal + internal → 允许）
kgent journal begin               # op_id + kgent://confluence/<pageId|待建>
                                  #   --revision-before=<当前 version.number>
                                  #   --snapshot-content=<写前完整 storage XHTML>
读当前页面                         # version.number + 当前正文（create 跳过）
CAS：当前 version == expected_version（update/delete）否则 FAIL（页面不动）
格式桥：markdown → storage XHTML（桥外结构 → 拒绝构造，不静默丢弃）
acli / MCP 写：
  create  → POST page（space + parent + title + body）→ 新 pageId + version=1
  update  → PUT 条件更新（body + version.number = 当前+1）；409 = 版本冲突
  delete  → DELETE page（进回收站；purge 不做）
kgent journal end                 # --revision-after=<写后 version.number>
                                  #   --snapshot-after=<写后完整 storage XHTML>
读回校验                           # GET + storage 正文比对（哈希）
```

**undo 补偿**（`kgent undo` 产出计划，skill 执行）：

| Op | 补偿 | 新鲜度（fail closed） |
|---|---|---|
| update | 取台账 revision_before 历史正文 → 按当前 version+1 条件重写（新版本，历史保留） | 当前 version == version_after，否则拒绝 |
| create | DELETE → 回收站 | 同上 |
| delete | 回收站恢复端点；退化路径 = 显式申报人工恢复 | 同上 |
| archive/unarchive | 不适用（backend 不支持 archive） | — |

已知限制如实陈述：update 补偿是「重写为新版本」不是原地还原（Confluence Cloud
无原地恢复端点；页面历史可见补偿写）；delete 若被回收站清空或恢复端点不可得，
只申报不硬来；补偿非原子（ADR 0005 同立场）。

## kgent CLI 侧改动（Python 足迹）

1. **config schema**（`config/schema.py`）：backend defaults 增 `spaces`
   （默认 `[]`，list[str] 校验——非 list 或含非 str → ConfigError）。`type`
   枚举零扩动（`skill|cli|mcp` 不变；confluence 恒 `skill`）。既有后端零改动。
2. **adapter**（`adapters/confluence.py` 新 + `adapters/__init__.py` 注册）：
   `CliCapabilityAdapter` 子类驱动 `acli`（win32 解析沿用 lark-cli.cmd 模式）；
   capabilities 声明 document_search + document_storage 的**只读子集**（无
   `.delete`/`.archive`/`.unarchive` 特性键）+ wiki 块（spaces list/create、
   node create）；`_native_id` 校验 pageId 全数字。document write 车道保持
   `NotImplementedError`（与 dingtalk/wecom 同形）。fidelity 声明进
   `adapters/fidelity.py`（storage XHTML → markdown 有损方向）。
3. **格式桥 CLI**（`kgent formats`，ADR 0016）：`kgent formats to-markdown`
   / `to-storage-xhtml`，stdin → stdout；stdlib `html.parser` + `html.escape`；
   surface manifest 增两探针；docs-conformance 命令 regex 增 `acli`，
   `DOC_FILES` 增 confluence-integration（`tests/test_docs_conformance.py:21-35`）。
4. **台账**（`router/ledger.py`）：`MECHANISM_BY_BACKEND` 增
   `confluence → "version-revert"`、`HISTORY_HINT_BY_BACKEND` 增 confluence
   历史页提示、`INTEGRATION_SKILL_BACKENDS` 随之纳入——`kgent undo` 即产出
   指名 `confluence-integration` 的补偿计划。journal/undo 模块零改动
   （revision 字段本就是后端无关字符串）。
5. **setup**（`capabilities/detect.py`）：confluence 腿——探测传输阶梯
   （acli 存在性 + 认证探针；MCP 检测宿主配置含 Atlassian server）并报告有效
   传输；backend 条目 merge-on-rerun 写入（不自动 enable，与 local-fs 同规
   ——ADR 0001/0003 语义不变）。
6. **doctor**（`config/validate.py`）：`backends.confluence.enabled` 时只读
   ——有效传输三值报告；acli 在但未认证 → warn；阶梯全不可得 → 信息级
   `unavailable`（不报 error：配置存在 ≠ 承诺可用，ADR 0015）；spaces
   allowlist 非 list → error。doctor 保持只读。
7. **原生 URL**（`skills/urls.py` `native_url`）：增 confluence 腿（上表 URL 形式；
   slug 缺省退 id-only）。
8. **README**：联邦后端清单的 Confluence 从承诺变现实（摘掉「计划中」语气）；
   不扩承诺范围。

**零执行面新增的地方**：`kgent search` CLI fanout 不因 confluence 改变性质
（ADR 0004 后真实平台检索走 integration skill；adapter 检索车道为测试/hosted
车道存在，与三平台同位）；`kgent undo` 的 adapter 执行路径不适用 confluence
（补偿由 skill 执行）；journal schema 不动。

## Tier 与失败模型

**Tier: high（覆盖性写 + 删除 + 组织知识面）。** 失败模型逐项：

| 失败 | 机制性防御 | 残余风险 |
|---|---|---|
| 覆盖并发写（他 agent/人） | Confluence `version.number` CAS：条件更新 + 写前 journal revision_before；409 → FAIL 页面不动 | 同刻写且 version 碰巧未动不可能（Confluence 每写必 +1）——CAS 完备；残余在 undo 重写窗口（下方） |
| undo 埋掉后续写 | 单层新鲜度：当前 version == 台账 version_after 否则拒绝；重写本身按当前 version+1 条件 | version 匹配后、重写落地前的窄窗口（与 0005 平台补偿同量级，非原子） |
| 格式桥丢内容 | 写前 `--snapshot-content` 完整 storage XHTML 快照 + 读回校验；桥外结构写拒绝；已知限制明示 | 用户对占位/降级语义的误解——skill 文档义务；快照是唯一完整恢复途径 |
| 删除后不可恢复 | Confluence 回收站（非 purge）；undo 走恢复端点 | 回收站被人工清空 / 恢复端点不可得 → 只申报不硬来（已知限制） |
| CQL 注入（查询串破坏 space 限定） | 查询串转义是负向约束 + hypothesis property 测试；allowlist 由代码注入非字符串拼接信任 | —（转义正确则无残余；escape 缺陷由 property 网捕获） |
| URI 混淆/跨后端 | `uri.py` 既有校验 + `_native_id` pageId 全数字校验 | — |
| 传输歧义（acli 与 MCP 行为差） | 阶梯按环境一次性裁决 + Gate 复核；密闭测试只认 acli 腿；MCP 腿 docs-pin + agent evals | MCP 工具面与 acli 的输出差异在运行时才暴露——已知限制如实陈述 |
| 速率限制（Cloud REST 限额） | `RetryBudget` 既有 429 退避（不计预算） | 长时限限流下的写失败 → journal end failed 显式落账 |
| 凭据泄漏 | 凭据只在 acli/宿主 OAuth；kgent 不读不存；输出掩码 | acli store 自身被攻破——超出 kgent 威胁模型 |
| spaces allowlist 配错（漏敏感空间） | 默认 `[]` = 全部可达；allowlist 是**收窄**手段不是保护边界——敏感空间治理归 Confluence 权限侧（spec 明示，不给虚假安全感） | 用户误以为 allowlist 是保密机制——skill 文档义务 |
| setup 静默启用改变既有 fanout | setup 不自动 enable；merge-on-rerun 不覆盖用户已改条目 | — |

## 验收标准（可执行）

**A1 acli 探针（gated，real，非默认 gauntlet）**：`tools/confluence-probe.sh`
对真实 Cloud 站点按序验证 REQUIRED 面：CQL 搜索返回 JSON、页面读取含
`version.number` + `body.storage`、页面 create（sandbox 空间）→ version=1、
条件 update（version+1）→ 成功、过期 version update → 409/拒、delete → 回收站、
回收站恢复端点可用、spaces list 可枚举、JSON 输出可解析。凭据缺失 → 显式跳过
消息（不 fail）。**探针未过不得宣称 confluence e2e 可用**（ADR 0015 后果条款）；
探针通过是 impl PR 关闭的前置（或显式豁免记录进 EVIDENCE）。

**A2 config/schema（pytest）**：含 `backends.confluence`（type: skill,
skill_name: confluence-integration, trust_zone: internal, spaces 缺省）的
config 经 `load_config_dict` 通过且 defaults 补全 `spaces: []`；
`spaces: ["ENG", "HR"]` 通过；`spaces: "ENG"`（非 list）与
`spaces: [1, 2]`（非 str 元素）→ ConfigError；`mode`/`remote` 键用于
confluence 不报错（backend defaults 通用，语义上忽略）；既有后端条目行为与本
PR 前完全一致（负向：type 枚举、loader 禁改键清单均零扩动）。

**A3 adapter（pytest + wire fake）**：fake acli subprocess（`tests/fakes/
fake_cli.py` 模式）下：CQL search → SearchResult 映射正确（URI、native_url、
spaceKey）；read → 格式桥 markdown 输出 + version 进 metadata；wiki capability
声明含 spaces list/create + node create；document write 车道
（create/update/delete document）→ `NotImplementedError`；`_native_id`
拒绝非数字 pageId 与外来后端 URI；fidelity 声明存在且含 storage→markdown 方向。
CQL 转义 hypothesis property：含 `"+-&|!(){}[]^~*?:\/` 与引号/反斜杠的查询串
生成的 CQL 恒可解析且 space 子句不被破坏（对抗语料含 `") OR type=page` 类逃逸尝试）。

**A4 格式桥（pytest + hypothesis）**：最小子集结构 round-trip
（markdown→XHTML→markdown 恒等或规范等价）；桥外结构（宏、附件占位、脚本标签）
→ 读方向降级为占位 + 声明、写方向拒绝；对抗语料：`<script>`、`<ac:structured-macro>`
伪嵌套、畸形嵌套 XHTML → 不崩溃、脚本内容剥离转义、输出为合法 markdown；
`kgent formats to-markdown` / `to-storage-xhtml` 进 `tools/surface-manifest.txt`
且 artifact-smoke 探针通过。

**A5 台账/undo（pytest）**：confluence 写 op 落账后 `kgent undo` 产出计划：
`mechanism: "version-revert"`、`integration_skill: "confluence-integration"`、
`revision_before/after` 为 version 数字串；当前 version ≠ version_after →
计划 `rejected`（FM2/FM3 既有语义零改动）；`HISTORY_HINT` 含历史页指引。

**A6 skill 纪律 docs-pin（pytest，hermetic）**（`test_localfs_docs_pins.py`
模式）：confluence-integration SKILL.md 必须携带——Gate 阶梯三条（acli → MCP →
优雅禁用）与凭据掩码、写入纪律块（route → journal begin → CAS → 写 → journal
end → 读回）、CQL 转义规则、格式桥有损披露与「桥外内容编辑会丢失该结构」警告、
spaces allowlist 收窄语义（不是保密边界）、不向用户引用 `kgent://` URI、undo
补偿表（含「重写为新版本非原地还原」明示）、已知限制节（blog/whiteboard/
database/附件/页面移动/purge 不支持）。docs-conformance：SKILL.md 全部 CLI 示例
（kgent / acli）对安装后工件 `--help` 可解析（regex 扩 `acli` 后）。

**A7 real e2e（opt-in，`real` 标记，sandbox 空间）**：凭据可得时——
create space（或复用 sandbox 空间）/ node / page → read → 条件 update → 过期
CAS 拒绝且页面未动 → delete → undo（回收站恢复）→ 全程 journal begin/end 成对
、op_id 含 uuid、revision 为 version 数字串、native URL 可构造。运行后 stray
清扫（sandbox 空间内本 PR 创建的页面清点）。默认 gauntlet 不含此腿。

## Setup plan（依赖逐项论证）

| 依赖 | 论证 |
|---|---|
| `acli`（用户自装，主传输） | 官方维护、API token 认证与三平台 CLI 同构、kgent 全部密闭测试基建以 CLI 为形状（ADR 0015）；不打包不代装——setup 只探测，缺失 → MCP 兜底或 `unavailable` |
| Atlassian Remote MCP（宿主侧，兜底传输） | 零 kgent 侧依赖：宿主 MCP 配置即可；代价（准入客户端、不可密闭测试）由 ADR 0015 如实记录 |
| 无新 Python 依赖 | 格式桥 = stdlib `html.parser`/`html.escape`；HTTP 全部在 acli/MCP 侧，kgent 不发 HTTP；`dependencies = []` 保持 |
| pytest + hypothesis 套件扩展 | A2–A6 纯 Python 层进既有 tests/（adapter fake 沿用 `tests/fakes/`）；无新测试框架 |
| agent evals（发布门，非本 spec 门） | `evals/skills/platform-via-integration-evals.json` 增 confluence 腿（读/写/undo 各一），跑在凭据可得环境；分区规则依 evals/README |
| sandbox 空间（运行时前提，非代码依赖） | real e2e 与探针的目标空间；key 经环境变量传入，缺省跳过——不留硬编码租户坐标 |

## Out of scope（后续 spec）

Jira、blog posts、whiteboards、databases、附件/媒体读写、宏读写、页面跨空间移动、
回收站 purge、DC/Server（PAT 认证，REST v1）、本地缓存/增量同步（现纯 live 查询）、
语义检索、空间权限管理、`type: mcp` 的 adapter 化（MCP 现仅 skill 层工具）、
kgent hosted backend 交互。
