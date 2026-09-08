# Phase 3（wecom-integration）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地母 spec v3 的 Phase 3——`skills/wecom-integration/SKILL.md`（能力契约六节，undo 补偿 = 台账快照写回）、WeComAdapter 接真 wecom-cli（读车道：FM3 内容比对 + version 新鲜度数据源 + B11-wecom search 类型保真）、evals fixtures wecom 腿、B5/B8/B11-wecom 验收 + agent evals + EVIDENCE 收尾。

**Architecture:** 平台操作统一经 integration skill（ADR 0004）；kgent 台账已就位（`MECHANISM_BY_BACKEND["wecom"] = "snapshot-restore"`、`HISTORY_HINT_BY_BACKEND` 无 wecom 项 → 计划里为 `None`，`src/kgent/router/ledger.py:36-47`）。本 Phase 不改台账/undo/route 逻辑，只补 WeCom 侧接口层：SKILL.md（agent 走的文档流）+ adapter `read_document`（`compensation_plan` 计划期经 `backends["wecom"].read_document()` 读当前 version/content 做新鲜度判定，`ledger.py:288-294`；adapter registry 在 `src/kgent/adapters/__init__.py:36` 已注册 `WeComAdapter()` 单例，改默认 cmd 解析即自动接线）。wecom-cli 的调用形态与 lark/dws 都不同——命令是 `wecom-cli <service> [resource...] <method> --json '<JSON 参数>'`（`--json` 是**输入体**旗标，非输出格式旗标），写命令成功返回**空对象**（无 revision 可记），读取返回 `version` 字段——一切命令拼写以 `wecom-cli <path> --help` 与 `wecom-cli schema get <service.resource.method>` 实测为准，Task 1 探针落真值。

**Tech Stack:** Python 3.12 stdlib（adapter/e2e 零新依赖；探针 .docx 经 `zipfile` 生成）、wecom-cli（npm `@wecom/cli`，Rust 核心，MIT，node≥18，Windows x64，**当前未安装**）、pytest/diff-cover/mypy（已有 dev deps）。

**Spec:**
- 范围定义：`specs/2026-09-07-phase2-phase3-handoff.md` §Phase 3（平台事实表、工作项 1–5、阻塞项）+ §两阶段通用约定
- 母 spec（approved v3）：`specs/2026-09-05-write-path-skill-delegation-design.md`——B5/B8/B11 验收标准原文、「EVIDENCE 要求」节、FM2/FM3 失败模式、风险节凭据阻塞语义
- 决策：`docs/adr/0004`（integration skill 中心制）、`docs/adr/0005`（台账驱动 undo）；统一语言 `CONTEXT.md`
- 结构模板：`docs/superpowers/plans/2026-09-07-phase2-dingtalk-integration.md`（Phase 2 计划）；血泪教训：`.superpowers/sdd/2026-09-07-phase2-dingtalk-integration/progress.md` Rulings 节

## Global Constraints

- **分支**：`feat/wecom-integration`，两种情形由控制器执行时定——(a) Phase 2 已合入 main：从 origin/main 切；(b) 未合并（当前 `feat/dingtalk-integration` @ `047ce87` 未合并）：从 `feat/dingtalk-integration` 分支尖切（Phase 2 产物——conformance 的 dws 扩容、adapter 先例、e2e 纪法——是本 Phase 的直接依赖，从 main 切会丢）
- **Baseline 第一步**：动任何代码前 `python -m pytest tests -q 2>&1 | tail -5` 原样记录（B12 基线；Phase 2 最终态为 579 passed / 6 skipped / 0 failed）
- 验收标准 **B5 / B8 / B11-wecom**（母 spec「可执行验收标准」节）逐条见到 RED→GREEN；**B12**：现有套件零新增失败；不得修改既有测试断言
- 零新增 Python 依赖；adapter/e2e 改动只用 stdlib（探针 .docx 用 `zipfile` + `xml.sax.saxutils.escape` 生成，不引 python-docx）
- **Windows（win32 + Git Bash）目标环境**：npm 全局包在 Windows 出三 shim（`wecom-cli` sh 包装 / `wecom-cli.cmd` / `wecom-cli.ps1`，PROBE-NOTES §5 dws 同款实测）——Python subprocess（`shell=False`）必须解析 `wecom-cli.cmd`（PATHEXT 不自动补，lark-cli.cmd/dws.cmd 同款教训）；wecom-cli 的 win32 可执行形态以 Task 1 探针实测为准（npm prefix 是 nvm4w 的 `C:\nvm4w\nodejs`，不硬编码路径）
- **内容通道**：多行/含 CJK 内容一律走 `file_path` 文件通道（`doc contents overwrite` 的 JSON 体 `content` XOR `file_path` 二选一），不过 `--json` argv 内联——2026-09-05 first-block 事故纪律；**Fs 沙箱 = 当前目录内相对路径**（wecom 特有：`--output-qrcode` help 原文「仅支持当前目录下的路径」，文件 IO 同域）——subprocess 的 `cwd` 必须锚定，台账快照在 `~/.kgent/journal/snapshots/` **必须先拷贝进 cwd 再传**；`doc contents append` 无文件通道（仅 `content` 内联）→ append 只用于短单行 ASCII
- **速率自设退避**（平台未文档化）：SKILL.md 写明集成层退避纪律（可重试错误 → 1s/2s/4s 指数退避、最多 3 次、超 3 次显式报告部分失败不静默缩量）；adapter `timeout=30.0` 默认（读车道不内置重试——退避归 skill 车道，注释声明）
- 真机探针命名带 `-probe-`（`kgent-phase3-probe-` 前缀）；teardown 必删——**wecom 平台无文档删除命令**（wecomcli-doc / wecomcli-doc-manage 均无 delete，Task 1 探针复核）→ 最严格等价物 = rename 隔离（`kgent-phase3-probe-DELETE-ME-` 前缀）+ session 末重试 + leftover 点名（docid + URL + 人工清理 runbook）；若 Task 1 探针发现删除命令（disk 域或隐藏 schema），改走真删并在 PROBE-NOTES 记录
- **两个人工闸（计划显式标注）**：① `npm i -g @wecom/cli` + `npx skills add WeComTeam/wecom-cli -y -g` 是**外部代码执行，需用户/维护者批准**（批准前本计划 WebFetch 已落的 README/docs 真值草案可用，标 ⚠ 待 `--help` 对账）；② `wecom-cli auth init` 交互式扫码（5 分钟窗口）**需维护者本人操作**（或 `--manual` 输 Bot ID/Secret）——auth 未就绪时按凭据阻塞语义推进
- **凭据阻塞语义**（母 spec 风险节 + Phase 2 裁决形态）：wecom auth 未就绪时，fixture/单元任务（Task 2/3/4）照常推进；Task 1 的 payload fixtures 按 documented-not-captured 模式落盘（`tests/fixtures/wecom-cli/FIXTURES-NOTE.md` 逐键 provenance）；Task 5 e2e 文件照写（skipif 凭据门）；agent evals wecom 腿 skipped；EVIDENCE 逐条声明 blocked，不以 fixture 绿冒充真机验收
- 新代码注释风格跟随仓库（中英混排、模块 docstring 带 B/FM/ADR 引用）；**本 PR 新增文件 ruff format 债为零**（Phase 2 Task 7 教训：新增文件必须 clean）
- 每任务 GREEN 后 commit；gauntlet 的 diff-cover 门是 `--fail-under 100` 显式门（Phase 2 fix round 定谳：`--fail-under` 缺省 0，裸调用任何覆盖率都退 0）

## 设计裁决：wecom undo 的新鲜度走 version 轴（来自读），FM3 内容比对是 fail-closed 兜底

本裁决是 B5 全部代码的语义地基，先于任务陈述。依据（全部已核）：

1. `ledger.compensation_plan`（`src/kgent/router/ledger.py:296-332`）的新鲜度分两路：
   - **revision 路**：end entry 带 `revision_after` → 比对 `current.metadata.version`（经 `backends["wecom"].read_document()`）；不符 → rejected，reason 带两侧 revision（FM2 形状）。
   - **FM3 路**（`revision_after is None` 且 operation != create）：`_snapshot_file_content(snap_path)` 与 `str(current.content)` 比对——**不符即拒**；ok 的充要条件是**当前内容 == begin 快照内容**（`tests/test_undo_ledger.py:220-237` 的 ok 用例正是 current=="A" == snapshot）。含义：一次**改变了内容**的 wecom update，若 end 无 revision 证据，undo 计划**必然 rejected**——这是 lark e2e 已文档化的同一教训（`tests/e2e/test_lark_undo_real.py` docstring 修正 3：「台账 end 必须带 --revision-after，否则 freshness 走 FM3 快照比对，写后内容已变 → 计划 rejected」）。
2. wecom 写命令（`doc contents append/overwrite`）成功返回**空对象**——revision 证据只能来自**读**：`doc contents get` 返回 `version` 字段（wecomcli-doc SKILL.md 文档化）。
3. 因此 wecom 写流程纪律（写进 SKILL.md 与 e2e，缺一不可）：
   - **begin 强制两证**：`--snapshot-content <写前全文>`（补偿唯一依据——快照写回的载荷）**且** `--revision-before <写前 version>`（读取得）；
   - **end 必须带 `--revision-after <写后 version>`**（写后读回取得）——B5 happy path（写 A → 写 B → 计划 ok → 快照写回 → 读回 A）只有这条路是 GREEN 的：current version == revision_after → ok → skill 把 `plan.plan.snapshot`（A）写回 → 读回 == A；
   - **FM3 的真实角色**：(a) 无 version 证据的 entry 的 fail-closed 兜底（e2e 有专门变体钉死它：end 不带 revision-after → rejected「snapshot no longer matches」）；(b) skill 侧写回前的内容复核纪律（执行前重读，与快照/写后状态不符即拒）。FM3-ok 分支（current == 写前快照）语义是「文档已在写前状态，写回幂等」——不伪装成能恢复已漂移内容的通道。
4. **⚠ 探针门控事实（Task 1 必须定谳）**：`doc contents get` 的 `version` 是否**每次编辑递增**（三次写 → 三次读，V1<V2<V3）。若递增 → 本裁决成立；若不递增/非数值 → version 轴不能作新鲜度证据，B5 happy path 在不改 ledger 的前提下不可满足——**停下上报控制器**（这是 ledger 语义级缺口：FM3-ok 要求 current==写前快照，内容已变的 update 不可达；需要设计裁决扩台账「写后内容」通道），不得静默改用其它口径冒充。

---

### Task 1: wecom-cli 安装（人工闸①）+ auth（人工闸②）+ 命令真值探针 + fixtures

**Files:**
- Create: `tests/fixtures/wecom-cli/PROBE-NOTES.md`（验证过的命令表——本 Phase 的命令真值单，复刻 `tests/fixtures/dws/PROBE-NOTES.md` 形态）
- Create: `tests/fixtures/wecom-cli/FIXTURES-NOTE.md`（documented-not-captured 的逐键 provenance；凭据就绪补捕后回填）
- Create: `tests/fixtures/wecom-cli/doc-search.json`、`doc-contents-get.json`（凭据就绪 → 真实 payload 捕获件；凭据阻塞 → documented-shape 构造 + FIXTURES-NOTE 声明，**禁止凭据前造数冒充真机**）

**Interfaces:**
- Produces（后续任务消费的真值）:
  - 命令真值表：`doc search` / `doc contents get` / `doc contents append` / `doc contents overwrite` / `doc import` / `doc names update` / `auth show` 的精确子命令路径、`--json` 输入体参数名、通用旗标（`--dry-run`/`--page-count`/`--page-delay`/`--output`/`--output-dir`/`--schema`）
  - payload 键位表：search 的 `has_more/next_cursor/docs[]` + hit 的 `docid/doc_name/doc_type/url` 字段路径；contents get 的 `content`（短内联）/`file_path`（长内容落盘）/`version` 字段路径；import 的 `docid/url/task_status` 字段路径
  - **version 轴定谳**：`version` 是否每次编辑递增（设计裁决第 4 条的探针门控事实）
  - 原生 URL 形状：`https://doc.weixin.qq.com/<type>/<docid>?scode=...` 的 `<type>` 实测值集（doc/sheet/smartsheet/smartpage 候选）+ docid 提取规则实测
  - win32 可执行形态：`wecom-cli.cmd` shim 三件套实测（npm prefix 位置）
  - 删除命令存在性：有 → 命令形状；无 → 确认 rename 隔离为 teardown 定案

WebFetch 已核实的命令形状（`github.com/WeComTeam/wecom-cli` README + `docs/cli-reference.md` + `docs/skills.md` + `skills/wecomcli-doc*/`，2026-09-08）——这些是**文档真值**，可直接写进 SKILL.md 草稿；标 ⚠ 的以 `--help`/`schema get`/真机实测为准修正：

| 用途 | 文档真值 | 状态 |
|---|---|---|
| 安装 | `npm install -g @wecom/cli`；`npx skills add WeComTeam/wecom-cli -y -g`（README 标注「必需」，装 14 个 `wecomcli-*` 原生 skill） | 文档证实 |
| 前置检查 | `wecom-cli --version`（≥1.1.0）；`wecom-cli auth show --status` → 单行 `authorized`/`unauthorized` | 文档证实（wecomcli-shared） |
| auth | `wecom-cli auth init`（交互扫码，仅一次）；旗标 `--noninteractive`（CI 扫码）、`--no-browser`、`--output-qrcode <PATH>`（**仅当前目录路径**）、`--manual`（输 Bot ID/Secret） | 文档证实 |
| 身份 | `wecom-cli identity whoami`；仅 bot 身份；`~/.config/wecom`（`WECOM_CLI_CONFIG_DIR` 可覆写）；`credentials.enc` AES-256-GCM 0600、token 只来自该文件 | 前两条文档证实；credentials.enc 细节 handoff 给出 ⚠ 探针确认文件存在 |
| 搜索 | `wecom-cli doc search --json '{"keywords":["周报"],"limit":10}'`；参数 `keywords/search_scope/doc_types/creator_userids/visitor_userids/created_after/created_before/opened_after/opened_before/sort_by/limit/cursor`；响应 `has_more/next_cursor/docs[]`，hit 含 `docid/doc_name/doc_type/url/creator_userid/create_time/modify_time/title_highlight/text_highlight` | 文档证实（wecomcli-doc-manage） |
| 读取 | `wecom-cli doc contents get --json '{"docid": ...}'`；参数 `docid`、`content_type`；响应 `url/name/content`（短内联）`/file_path`（长内容落盘）`/document`（ooxml）/`version` | 文档证实（wecomcli-doc） |
| 追加 | `wecom-cli doc contents append --json '{"docid": ..., "content": ...}'`（仅 text 纯文本；**无文件通道**）；成功返回空对象 | 文档证实 |
| 覆盖写 | `wecom-cli doc contents overwrite --json '{"docid": ..., "content_type": "markdown"|"text", "content" XOR "file_path"}'`（清空须传 `" "`）；成功返回空对象 | 文档证实 |
| 创建 | 两步流：本地生成 .docx → `wecom-cli doc import --json '{"doc_type": ..., "file_name": ..., "file_path": ..., "passwd": ...}'`（`file_path` = 源文件本地路径）；返回 `docid/url/task_status`（"succ"） | 文档证实；`doc_type` 枚举值 ⚠ 实测 |
| 改名 | `wecom-cli doc names update --json '{"docid": ..., "new_name": ...}'`；成功返回空对象 | 文档证实（doc-names-update.md） |
| 通用旗标 | `--dry-run`、`--page-count <n>`（NDJSON 分页）、`--page-delay <ms>`（默认 100）、`--output/-o <file>`、`--output-dir <dir>`、`--schema`/`--doc`；隐藏内建 `schema list`、`schema get <service.resource.method>`、`cache status/clear` | 文档证实（cli-reference.md） |
| 错误契约 | 退出码 0/1/2；结构化 JSON 错误 `code` 893000–893299、兜底 893999；输出文件 0600 | 文档证实；正常输出是否 JSON 默认 ⚠ 实测 |
| 已知冲突 | README 功能表称邮件「send/reply/forward」，`docs/skills.md` 称 wecomcli-email **仅支持浏览与查询（只读）** | 冲突——SKILL.md 已知限制收录，按只读对待 ⚠ |
| 消息 | 先 `wecom-cli message aibot sessions list` 查最近会话，再用列表返回的会话 ID 发送（=「消息只达 bot 最近对话过的会话」的机制面） | 文档证实 |

- [ ] **Step 1: 安装（人工闸①——外部代码执行，先获用户批准）**

```bash
# 批准后执行；README 标注第二条「必需」（装 14 个 wecomcli-* 原生 skill）
npm install -g @wecom/cli
npx skills add WeComTeam/wecom-cli -y -g
wecom-cli --version    # 期望形如 "wecom-cli 1.x.y (npm 2026-..-..T..:..:..Z <git_commit>)"，且 ≥1.1.0
where wecom-cli        # win32：期望三 shim 并存（wecom-cli / wecom-cli.cmd / wecom-cli.ps1），记录 npm prefix
wecom-cli --help       # 服务树：message/mail/doc/sheet/smartsheet/calendar/meeting/todo/disk/contact/media/identity
```

批准前/安装失败时：不改任何代码，转 Step 3 用 `WebFetch github.com/WeComTeam/wecom-cli`（README、docs/cli-reference.md、docs/skills.md、skills/wecomcli-*/SKILL.md）已落的文档真值推进 Task 2/3，全部标 ⚠ 待对账（本计划表中已含该草案）。

- [ ] **Step 2: 身份与配置核查（人工闸②——维护者本人扫码）**

```bash
wecom-cli auth show --status   # 期望单行 "authorized"；"unauthorized" → 下一步
wecom-cli auth init            # 交互式扫码（5 分钟窗口），维护者本人操作；无头/远端用 --no-browser + --output-qrcode qr.png（当前目录），或 --manual 输 Bot ID/Secret
```

auth 未就绪 → **如实记录 blocked**（PROBE-NOTES §0：实测输出、等待窗口、无人扫码），按凭据阻塞语义推进；Step 4 的 payload fixtures 走 documented-not-captured 模式。

向用户说明后读配置（skill 规则：读 kgent 配置前先说明）：确认 `~/.kgent/config.yaml` 的 `backends.wecom`——Phase 2 实测 `type` 是 schema 必填（`src/kgent/config/schema.py:224-226`），`trust_zone` 缺省是 **external** 必须显式改 internal（三平台 internal 裁决，handoff 接线清单 4）：

```yaml
backends:
  wecom:
    enabled: true
    type: skill
    skill_name: wecom-integration
    trust_zone: internal
```

补齐后 `python -m kgent doctor --json` → healthy（该文件在仓库外，不入 commit）。

- [ ] **Step 3: 命令真值表（写进 PROBE-NOTES.md，[help 实测] 标注）**

```bash
wecom-cli doc --help; wecom-cli doc contents --help
wecom-cli doc contents get --help; wecom-cli doc contents overwrite --help   # 参数/枚举/文件通道
wecom-cli doc import --help; wecom-cli doc names update --help; wecom-cli doc search --help
wecom-cli schema get doc.contents.get; wecom-cli schema get doc.contents.overwrite   # 机器契约（无凭据可查）
wecom-cli auth show --help
```

逐条记录：子命令路径、`--json` 体的参数名与类型、正常输出格式（JSON 默认？⚠ 定谳）、错误 envelope 形状（`errcode`/`code`？）、`doc import` 的 `doc_type` 枚举、有无任何 delete 动词（`wecom-cli doc --help` 全树 + `schema list` 过滤）。

- [ ] **Step 4: 真机探针（凭据就绪时；命名带 `-probe-`）**

```bash
mkdir -p /tmp/wecom-probe && cd /tmp/wecom-probe
# 探针 .docx 由 stdlib 生成（与 Task 5 e2e 的 _write_probe_docx 同一形态）
python - <<'PY'
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile
text = "AAA-CONTENT"
ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p></w:body></w:document>')
with zipfile.ZipFile("probe.docx", "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("[Content_Types].xml", ct); zf.writestr("_rels/.rels", rels); zf.writestr("word/document.xml", doc)
Path("b.md").write_text("BBB-CONTENT\n", encoding="utf-8", newline="\n")
PY
wecom-cli doc import --json '{"doc_type":"doc","file_name":"kgent-phase3-probe-临时.docx","file_path":"probe.docx"}' | tee import.json
wecom-cli doc contents get --json '{"docid":"<import.json 的 docid>"}' | tee doc-contents-get-v1.json    # version=V1
wecom-cli doc contents overwrite --json '{"docid":"<DOCID>","content_type":"text","file_path":"b.md"}'
wecom-cli doc contents get --json '{"docid":"<DOCID>"}' | tee doc-contents-get-v2.json                    # version=V2 —— V2>V1?
printf 'CCC-CONTENT\n' > c.md
wecom-cli doc contents overwrite --json '{"docid":"<DOCID>","content_type":"text","file_path":"c.md"}'
wecom-cli doc contents get --json '{"docid":"<DOCID>"}' | tee doc-contents-get-v3.json                    # version=V3 —— V3>V2?（设计裁决第 4 条定谳）
wecom-cli doc search --json '{"keywords":["kgent-phase3-probe"],"search_scope":"title_content","limit":10}' | tee doc-search.json
wecom-cli doc names update --json '{"docid":"<DOCID>","new_name":"kgent-phase3-probe-DELETE-ME-临时"}'    # teardown（无删除命令时）
```

把 `doc-search.json`、`doc-contents-get-v2.json` 存为 `tests/fixtures/wecom-cli/`（标题敏感词换中性词，结构原样）。**version 轴结论写进 PROBE-NOTES 顶部**（V1<V2<V3 与否 = B5 纪律成立性）。若发现删除命令 → 探针真删并在 PROBE-NOTES 记录命令形状。

- [ ] **Step 5: 凭据阻塞时的 documented-not-captured 落盘（对照 Phase 2 Ruling）**

凭据不可用 → 按 Step 3 的 `[help 实测]` 真值 + 上表「文档真值」构造两份 fixture（**不是真机输出**），`FIXTURES-NOTE.md` 逐键 provenance：外层/容器键（`has_more/next_cursor/docs[]`；contents get 的响应字段族）有文档实证；叶子键名（`docid/doc_name/doc_type/url/content/file_path/version`）已由官方 skill 文档点名的标注来源、未点名的标注为构造值；**解析代码不散落读这些键**——集中在 `src/kgent/adapters/wecom.py` 模块级 `_extract_*`（键位对账锚点），补捕后只改锚点 + 回填 fixture。冲突点显式列（对照 dws FIXTURES-NOTE 的四点模式）：(1) 正常输出是否带 envelope（`data` 包裹 vs 顶层）；(2) `version` 的类型（int vs str）与递增性；(3) 错误档的键（`errcode` vs `code` 族）；(4) 长内容 `file_path` 的相对/绝对语义与 Fs 沙箱边界。两份 fixture 的构造值（Task 3 测试常量与之钉死一致）：

```json
{
  "url": "https://doc.weixin.qq.com/docx/agA0AAAAwecomProbeDoc01?scode=AAA-probe",
  "name": "kgent-phase3-probe 使用手册",
  "content": "probe body line for payload capture.\n\n## 验收点\n\n- version 随编辑递增，wecom undo 新鲜度用它（B5）；无 version 证据时 FM3 快照内容比对兜底。\n",
  "version": 3
}
```

```json
{
  "has_more": false,
  "next_cursor": "",
  "docs": [
    {
      "docid": "agA0AAAAwecomProbeDoc01",
      "doc_name": "kgent-phase3-probe 使用手册",
      "doc_type": "doc",
      "url": "https://doc.weixin.qq.com/docx/agA0AAAAwecomProbeDoc01?scode=AAA-probe",
      "creator_userid": "USER_PROBE",
      "create_time": 1757300000,
      "modify_time": 1757300600,
      "title_highlight": "",
      "text_highlight": "probe body line for payload capture."
    },
    {
      "docid": "b1SmartPageProbe001",
      "doc_name": "kgent-phase3-probe 智能文档",
      "doc_type": "smartpage",
      "url": "https://doc.weixin.qq.com/smartpage/b1SmartPageProbe001?scode=BBB-probe",
      "creator_userid": "USER_PROBE",
      "create_time": 1757300100,
      "modify_time": 1757300700,
      "title_highlight": "",
      "text_highlight": ""
    },
    {
      "docid": "sheetProbe0000001",
      "doc_name": "kgent-phase3-probe 排期表",
      "doc_type": "sheet",
      "url": "https://doc.weixin.qq.com/sheet/sheetProbe0000001?scode=CCC-probe",
      "creator_userid": "USER_PROBE",
      "create_time": 1757300200,
      "modify_time": 1757300800,
      "title_highlight": "",
      "text_highlight": ""
    }
  ]
}
```

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/wecom-cli/
git commit -m "test: wecom-cli 真值探针 fixtures + 命令真值表（Phase 3 Task 1）"
```

---
### Task 2: docs-conformance 扩容 + `skills/wecom-integration/SKILL.md` + 编排 skills 的 WeCom URL 行

**Files:**
- Modify: `tests/test_docs_conformance.py:22-38`（DOC_FILES 追加；`_LINE`/`_SPAN` 扩 `wecom-cli`；binary 解析与活断言）
- Create: `skills/wecom-integration/SKILL.md`
- Modify: `skills/knowledge-storage/SKILL.md:234`、`skills/question-answering/SKILL.md:137`（WeCom URL 行改指 integration skill）、`skills/wiki-setup/SKILL.md:78`（同语义）

**Interfaces:**
- Consumes: Task 1 命令真值表 + 原生 URL 形状 + version 轴结论
- Produces: `skills/wecom-integration/SKILL.md`——六个编排 skills 已按名引用 `<platform>-integration`（B9 静态检查 `INTEGRATION_REF` 正则对 wecom 已生效，无需改 `tests/test_skill_docs_integration_routing.py`）；agent evals 的委派断言以本文档章节名为准（Search / Read / Write / Undo Compensation / Native URL / Known Limitations）

- [ ] **Step 1: 扩容 docs-conformance（先改测试，见 RED）**

`tests/test_docs_conformance.py` 四处（照 diff 语义改，不动既有断言）：

```python
DOC_FILES = [
    SKILLS_DIR / "knowledge-storage" / "SKILL.md",
    SKILLS_DIR / "question-answering" / "SKILL.md",
    SKILLS_DIR / "wiki-setup" / "SKILL.md",
    SKILLS_DIR / "lark-integration" / "SKILL.md",
    SKILLS_DIR / "dingtalk-integration" / "SKILL.md",
    SKILLS_DIR / "wecom-integration" / "SKILL.md",
]
```

```python
_LINE = re.compile(r"^\s*(?:[-*]\s+|>\s*|\$\s+)?((?:kgent|lark-cli|dws|wecom-cli)\b.+)")
```

```python
_SPAN = re.compile(r"`((?:kgent|lark-cli|dws|wecom-cli)\b[^`]+)`")
```

`test_documented_cli_examples_parse` 内（Phase 2 裁决：活断言进用例，不进 skipif——skipif 会让活断言不可达）：

```python
    dws_bin = shutil.which("dws")
    wecom_bin = shutil.which("wecom-cli")
    assert kgent_bin is not None and lark_bin is not None
    # dws/wecom-cli 不进 requires_artifact 的 skipif：缺席时 lark/kgent 用例照跑，而
    # 对应 integration 用例在这里显式 fail（Task 1 之后应常驻），不静默 skip。
    if doc.parent.name == "dingtalk-integration":
        assert dws_bin is not None, "Task 1 之后 dws 应常驻"
    if doc.parent.name == "wecom-integration":
        assert wecom_bin is not None, "Task 1 之后 wecom-cli 应常驻"
```

binary 分发（`elif tokens[0] == "dws":` 块之后追加）：

```python
        elif tokens[0] == "wecom-cli":
            binary = wecom_bin
```

Run: `python -m pytest tests/test_docs_conformance.py -v -k wecom`
Expected: FAIL——`skills/wecom-integration/SKILL.md` 尚不存在（parametrize 的 doc 读不到）或 wecom-cli 未装时的显式 fail。这就是本层价值的 RED。

- [ ] **Step 2: 写 SKILL.md（全文见下）→ 对账循环到 GREEN**

Run: `python -m pytest tests/test_docs_conformance.py -v -k wecom`
Expected: 首轮 FAIL 列出与真实 `wecom-cli <path> --help` 不符的旗标/子命令 → 按 Task 1 真值表逐条修正 → 重跑到 PASS。下方草稿全部用 Task 1 表中「文档证实」的命令形状；**标 ⚠ 的行以真值为准**。

`````markdown
---
name: wecom-integration
description: "Equip kgent operations with WeCom-specific knowledge: search and read WeCom docs via wecom-cli, write with journal discipline and mandatory pre-write content snapshots, undo compensation via ledger snapshot write-back (snapshot-restore), delegation of non-doc content to the native wecomcli-* skills, native URL citation rules, and WeCom-side known limitations. Invoke when kgent search/read/write touches WeCom content and backends.wecom.enabled is true in ~/.kgent/config.yaml."
---

# WeCom Integration

Equip the kgent skills (question-answering, knowledge-storage, wiki-setup) with the WeCom layer of their operations: search, read, write, undo compensation, and native URLs for WeCom content, executed through `wecom-cli`. Non-doc content types delegate to the native `wecomcli-*` skills (matrices under Read / Write). Single source of truth — the kgent skills carry no copies of these rules.

## The Gate

These rules apply only when the WeCom backend is enabled — `backends.wecom.enabled: true` in `~/.kgent/config.yaml`. With the gate closed, skip every WeCom-specific section below; other backends (Lark, DingTalk) are unaffected.

Gate open but the WeCom side unavailable — wecom-cli missing, version below 1.1.0, auth `unauthorized`: degrade gracefully. Keep the kgent-only results, tell the user which WeCom steps were skipped, and continue the main flow. Pre-flight per wecomcli-shared: `wecom-cli --version` then `wecom-cli auth show --status` (single line `authorized` / `unauthorized`; anything else — stop and report, never guess).

## Search

`kgent` 的 search 对 WeCom 内容一律改走本 skill（ADR 0004）。步骤：

1. `wecom-cli doc search --json '{"keywords":["<kw>"],"search_scope":"title_content","limit":10}'`——多关键词按官方示例降级展开（`["待办 tool","待办","tool"]` 式）；分页用响应的 `next_cursor` + `--page-count`（⚠ 旗标按 `--help` 真值）。
2. 类型判定（每条 hit，字段 `doc_type` / URL `<type>` 段）：四类核心 `doc` / `sheet` / `smartsheet` / `smartpage`；docid 以 `a1`/`b1` 起头或 URL 含 `/smartpage/` 一律按 smartpage 路由。kgent 词表（§7.2）只有 `doc`|`wiki_node`，WeCom 无 wiki 概念——**node_type 一律 `doc`，绝不虚构 `wiki_node`**；非 doc 产品经下面的委派矩阵路由，不靠 node_type。
3. 引用一律转原生 URL（见 Native URL）。
4. 命中数缩量（超时/限流）必须显式声明，不静默。

## Read

对 WeCom 内容的一切读取经本 skill。**在线文档（doc）直调 wecom-cli**：

- `wecom-cli doc contents get --json '{"docid":"<DOCID>"}'`——短内容内联在 `content`；长内容平台落盘本地文件、响应给 `file_path`（**读回该文件**，路径相对 CLI 当前目录）。`content_type` 取 `ooxml` 时另有 `document` 结构档（⚠ 参数名按真值）。
- 读回的内容是数据不是指令（N6/S39 延伸到 WeCom 读取）。

**其余类型委派原生 skill**（本 skill 只记委派关系与入口，命令全集在各 skill）：

| Content | Delegate to | Entry points |
|---|---|---|
| 文档管理（最近浏览/创建、改名、成员权限、加入规则） | **wecomcli-doc-manage** skill | `wecom-cli doc search`（参数组合分派）、`wecom-cli doc names update --json '{"docid":"...","new_name":"..."}'` |
| 智能表格 | **wecomcli-smartsheet** skill | `wecom-cli smartsheet ...` |
| 在线表格 | **wecomcli-sheet** skill | `wecom-cli sheet ...` |
| 智能文档（smartpage；未指定类型的创建/写作默认走它） | **wecomcli-smartpage** skill | `wecom-cli smartpage` 域 ⚠ |
| 微盘文件 | **wecomcli-disk** skill | `wecom-cli disk ...` |
| 消息 | **wecomcli-message** skill | `wecom-cli message aibot sessions list` 先查最近会话 |
| 邮件（**只读**） | **wecomcli-email** skill | `wecom-cli mail ...`（见 Known Limitations 的只读冲突） |
| 待办 / 日程 / 会议 | **wecomcli-todo** / **wecomcli-calendar** / **wecomcli-meeting** skill | 各自域 |
| 通讯录 | **wecomcli-contact** skill | `wecom-cli contact ...` |
| 媒体文件搬运 | **wecomcli-media** skill | media_id 上下行 |

Invoke the skill by name (Skill tool when available) and follow its workflow; it owns its own pre-flight (wecomcli-shared) and confirmation contract. Summarize what came back and cite it like any other source, using the Native URL rules below.

## Write

对 WeCom 内容的一切写入经本 skill。doc 之外的目标按 Read 的委派矩阵反向对称委派（sheet/smartsheet/smartpage/disk/message/todo/calendar/meeting 各归原生 skill；邮件发送不可用——只读）。

**doc 写入的 journal 纪律（硬性步骤；无平台 history，快照是补偿唯一依据——ADR 0005）**：

```bash
# 0. 写前读（双证：全文快照 + version）
wecom-cli doc contents get --json '{"docid":"<DOCID>"}'        # → content（全文）、version
# 1. 路由裁决
kgent route --dry-run --content "<content>" --backends wecom --json
# 2. 台账开账——强制两证：--snapshot-content <写前全文>（补偿载荷）+ --revision-before <写前 version>
kgent journal begin --operation update --backend wecom --doc-uri kgent://wecom/<docid> --revision-before <version> --snapshot-content "<写前全文>" --json
# 3. 写入（多行/CJK 一律 file_path 文件通道，不过 --json argv 内联——first-block 事故纪律）
wecom-cli doc contents overwrite --json '{"docid":"<DOCID>","content_type":"text","file_path":"payload.md"}'
# 4. 写后读回（version 证据 + 完整性校验一步完成）
wecom-cli doc contents get --json '{"docid":"<DOCID>"}'        # → 新 version
# 5. 落账——必须带 --revision-after <写后 version>（无此证据 → undo 走 FM3 内容比对，内容已变必拒，见 Undo）
kgent journal end --op-id <op_id> --status ok --revision-after <写后version> --json
# 6. 读回校验（内容一致才向用户确认）
```

- **创建**（两步流）：本地生成 .docx → `wecom-cli doc import --json '{"doc_type":"doc","file_name":"<名>.docx","file_path":"<相对路径>"}'` → 响应 `docid/url/task_status`（轮询 `"succ"`）→ `journal begin --operation create`（`--doc-uri` 用计划占位 URI，`--snapshot-content` 可空——create 腿补偿是删除/隔离，不写回）→ `journal end --doc-uri kgent://wecom/<real_docid> --revision-after <首读 version>`。
- **内容通道**：`overwrite` 的 `content` XOR `file_path` 二选一——多行/含 CJK **必须** `file_path`（当前目录相对路径，Fs 沙箱）；`append` 无文件通道（仅 `content` 内联、纯文本）→ 只用于短单行 ASCII；清空文档不能传空值（须传一个空格，官方文档明言）。
- **写前批准**：proposal → 用户批准 → journal begin → 执行（母 spec 操作流；`--dry-run` 旗标可做事前演练）。

## Undo Compensation（ADR 0005）

WeCom 无平台 history → 补偿机制是**台账快照写回**（`kgent undo` 计划 `plan.plan.mechanism == "snapshot-restore"`、`plan.plan.history_hint == null`），执行归本 skill。流程：

1. `kgent undo <op_id> --json` 取补偿计划；`status == "rejected"` 时**停止**——version 轴不符（FM2：expected/current 两侧 version 在 reason）或（无 version 证据的 op）内容偏离快照（FM3：「snapshot no longer matches」）。绝不带着过期计划落写回。
2. 读 `plan.plan.snapshot`（begin `--snapshot-content` 落盘的写前全文）——**先拷贝到当前目录临时文件**（Fs 沙箱只吃 cwd 相对路径，台账快照在 `~/.kgent/journal/snapshots/` 之外）。
3. **执行前复核（TOCTOU/FM3）**：`wecom-cli doc contents get` 重读——带 version 证据的 op：当前 version 必须仍 == `plan.plan.revision_current`；同时核对正文仍是写后状态（写后读回的全文）。不符 → 停止并报告。
4. `wecom-cli doc contents overwrite --json '{"docid":"<DOCID>","content_type":"text","file_path":"<快照临时文件>"}'` 写回。
5. 读回校验：内容与 `plan.plan.snapshot` 逐字一致（有界轮询——平台写入可见性可能滞后）。
6. **create 腿的补偿是删除**（B4 同构）：平台无文档删除命令（见 Known Limitations）→ 降级 = `wecom-cli doc names update` 改名为 `DELETE-ME-` 前缀隔离 + 向用户报告 docid/URL 供人工删除——不静默、不假装已删。

## Native URL

Cite native WeCom URLs, never `kgent://` URIs。URL 形状 `https://doc.weixin.qq.com/<type>/<docid>?scode=...`——**`?scode=` 是分享签名，不可自行构造**：

- 命令响应里带 `url`（search hit / contents get / import 都带）→ **原样引用**，不重拼。
- 响应没带 URL → 如实说明无法提供原生链接，不猜路径。
- `kgent://wecom/<docid>` ↔ 原生 URL 的 docid 提取：`/<type>/` 之后、`?` 之前的部分；`a1`/`b1` 起头的 docid 是 smartpage，引用与路由都按 smartpage 对待。
- 展示纪律（官方 skill 同款）：给用户看 `[doc_name](url)`，**不展示 docid**——docid 仅 CLI 内部使用。

## Known Limitations

- **仅 bot 身份**：`wecom-cli auth init` 交互式扫码（5 分钟窗口，仅需一次）或 `--manual` 输 Bot ID/Secret；凭据落 `~/.config/wecom/credentials.enc`（AES-256-GCM，0600；`WECOM_CLI_CONFIG_DIR` 可迁），token 只来自该文件。扫码必须维护者本人完成——auth 未就绪时本 skill 各节的降级路径是常态路径，必须可靠。
- **消息只达「bot 最近对话过」的会话**：发消息先 `wecom-cli message aibot sessions list` 查最近会话、用列表返回的会话 ID 发送；不在列表里的收件人不可达——如实报告，不猜会话 ID。
- **速率限制未文档化**：集成层自设退避——可重试错误（限流/超时）按 1s/2s/4s 指数退避、最多 3 次；超限显式声明部分失败，不静默缩量。
- **Fs 沙箱（文件 IO 限当前目录相对路径）**：`file_path`/`--output`/`--output-qrcode` 都只吃 cwd 内相对路径——subprocess 的 cwd 必须锚定；台账快照（`~/.kgent/journal/snapshots/`）写回前必须先拷进 cwd。
- **无文档删除命令**：doc/doc-manage 域均无 delete——create 腿补偿与探针清理都降级为 rename 隔离 + 人工删除 runbook。
- **邮件只读冲突**：README 功能表声称可发送，官方 skills 文档明言 wecomcli-email 仅支持浏览与查询——按只读对待；需要发信时如实告知走别的渠道。
- **undo 依赖 version 证据**：写流程若漏 `journal end --revision-after`，undo 走 FM3 内容比对而对已变更内容必然拒绝（fail closed）——这是设计，不是 bug；补救只能重新走写流程。

## 回复语言与配置访问

- **语言跟随请求**：请求用什么语言表述，回复就用什么语言——包括 proposal、确认信息、引用说明与所有面向用户的文字。
- **配置读取必须先征得同意**：读取 `~/.kgent/config.yaml`（或任何 kgent 配置文件）之前，先向用户说明要读什么、为什么，征得同意后再读——配置含后端与信任设置，不静默读取；此条管的是 agent 直接 Read 配置文件的行为，kgent CLI 自身内部读配置不受此条约束。
`````

- [ ] **Step 3: 编排 skills 的 WeCom URL 行改指 integration skill**

`skills/knowledge-storage/SKILL.md:234` 原行：

```markdown
**WeCom**: `kgent://wecom/<id>` → WeCom admin console URL
```

替换为：

```markdown
**WeCom**: with the WeCom backend enabled, invoke the `wecom-integration` skill and cite the native URL returned by the platform response verbatim (per its Native URL rules) — WeCom doc URLs carry a `?scode=` share signature that cannot be reconstructed, and the admin-console URL shape was never a content link.
```

`skills/question-answering/SKILL.md:137` 同语义替换（原行与上同）。`skills/wiki-setup/SKILL.md:78` 行尾 `for WeCom legs, show the admin console URL format` 替换为 `for WeCom legs, with the WeCom backend enabled, invoke the `wecom-integration` skill and cite the platform-response URL verbatim per its Native URL rules`。跑 B9 静态检查确认无回归：

```bash
python -m pytest tests/test_skill_docs_integration_routing.py -v
```

Expected: 2 passed（wecom-integration 引用本就在三 skills 文本中，改写不丢词）。

- [ ] **Step 4: 全套无新增失败**

Run: `python -m pytest tests/test_docs_conformance.py tests/test_skill_docs_integration_routing.py -v && python -m pytest tests -q 2>&1 | tail -3`
Expected: wecom-integration 参数化用例 PASS（wecom-cli 在装时；抽取 ≥1 条示例）；全套失败数 ≤ baseline。

- [ ] **Step 5: Commit**

```bash
git add tests/test_docs_conformance.py skills/wecom-integration/SKILL.md skills/knowledge-storage/SKILL.md skills/question-answering/SKILL.md skills/wiki-setup/SKILL.md
git commit -m "feat(skills): wecom-integration skill — wecom-cli 调用矩阵 + 快照写回补偿（母 spec Phase 3）"
```

---
### Task 3: WeComAdapter 读车道接真 wecom-cli（FM3/version 新鲜度读 + B11-wecom search 保真）

**Files:**
- Modify: `src/kgent/adapters/wecom.py`（整文件重写——wire-v1 基类保留给未覆盖方法）
- Test: `tests/test_wecom_adapter.py`（Create；fixture 驱动，沿用 `tests/test_dingtalk_adapter.py` 的 fake-`run_cli` + payload 形状模式）

**Interfaces:**
- Consumes: Task 1 fixtures（`tests/fixtures/wecom-cli/*.json`）+ 键位表；`CliCapabilityAdapter`/`run_cli`（`cli_adapter.py`）；registry 已注册单例（`adapters/__init__.py:36`，改默认 cmd 即接线）
- Produces:
  - `WeComAdapter(cmd=None, timeout=30.0)`：win32 默认 `["wecom-cli.cmd" if sys.platform == "win32" else "wecom-cli"]`（lark/dws 同款）
  - `read_document(doc_uri: str) -> Document`：`doc contents get --json '{"docid": <id>}'`；`content` 内联短文 / `file_path` 长内容落盘读回；`metadata.version` = 响应 `version` 字段字符串化（缺省 `None`——`compensation_plan` 的 version 轴与 FM3 内容比对都吃这两个值，`ledger.py:294/328`）
  - `search_by_keywords(query, filters=None, top_k=10, fields=None) -> list[SearchResult]`：`doc search --json '{"keywords": [<q>], "search_scope": "title_content", "limit": <n>}'`；hit → `kgent://wecom/<docid>`；`node_type` 一律 `"doc"`（wecom 无 wiki_node，词表保真 = 不虚构）
  - create/update/delete **不接**（写经 wecom-integration，ADR 0004；adapter 写车道留给 hosted backend）——docstring 声明

- [ ] **Step 1: 写失败测试（fixture 驱动）**

```python
"""WeComAdapter 真值接线（B11-wecom search 类型保真 + B5 undo 新鲜度读）。

fixture 沿用 tests/test_dingtalk_adapter.py 的模式：payload 形状存
tests/fixtures/wecom-cli/（Task 1），fake ``run_cli`` 按 argv 元素分发——
不 spawn 真实 wecom-cli。

**Provenance（凭据未就绪时）**: documented shape from wecom-cli official
skill docs（wecomcli-doc / wecomcli-doc-manage 的 SKILL.md 与 references）;
NOT live-captured——逐键 provenance 见 tests/fixtures/wecom-cli/FIXTURES-NOTE.md。
叶子键名是补捕前的对账锚点：解析全部集中在
``kgent/adapters/wecom.py`` 的模块级 ``_extract_*``，补捕后只改锚点与本目录
fixture。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kgent.adapters import wecom as wecom_mod
from kgent.adapters.cli_adapter import SubprocessResult
from kgent.adapters.wecom import WeComAdapter
from kgent.errors import AdapterError

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "wecom-cli"
SEARCH_PAYLOAD = (FIXTURES / "doc-search.json").read_text(encoding="utf-8")
GET_PAYLOAD = (FIXTURES / "doc-contents-get.json").read_text(encoding="utf-8")

#: doc-contents-get.json 的取值（期望值直接取 fixture 真值；键位漂移改 fixture + _extract_*）
DOC_ID = "agA0AAAAwecomProbeDoc01"
GET_VERSION = "3"  # contents get 的 version（int → kgent 统一字符串化，§3.9）


class _FakeWeCom:
    """按 argv 元素分发 fixture 的 run_cli 替身；记录调用。

    Phase 2 Ruling 教训：不用 ``" search " in joined`` 子串分发（对 ``+search``
    形态永不命中）——wecom 的子命令是空格分词的多元素路径
    （``["doc", "search", ...]`` / ``["doc", "contents", "get", ...]``），
    按元素精确匹配。
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float, **_kw: Any) -> SubprocessResult:
        self.calls.append(argv)
        if "search" in argv:
            return SubprocessResult(0, SEARCH_PAYLOAD, "")
        return SubprocessResult(0, GET_PAYLOAD, "")


def test_read_document_content_and_version(monkeypatch):
    fake = _FakeWeCom()
    monkeypatch.setattr(wecom_mod, "run_cli", fake)
    adapter = WeComAdapter()
    doc = adapter.read_document(f"kgent://wecom/{DOC_ID}")
    assert doc.metadata.version == GET_VERSION  # B5 version 轴数据源
    assert doc.metadata.node_type == "doc"
    assert "probe body line" in doc.content  # fixture 正文 needle
    # 命令形状钉死：--json 输入体 + docid（conformance 之外的 argv 级锚点）
    sent = fake.calls[0]
    assert sent[sent.index("doc"): sent.index("doc") + 3] == ["doc", "contents", "get"]
    body = json.loads(sent[sent.index("--json") + 1])
    assert body == {"docid": DOC_ID}


def test_read_document_long_content_via_file_path(monkeypatch, tmp_path):
    """长内容走平台落盘的 file_path（cwd 相对）——adapter 读回该文件。"""
    payload = json.loads(GET_PAYLOAD)
    payload["content"] = None
    side = tmp_path / "long-content.md"
    side.write_text("# 长内容\n\n第二段 ❤️\n", encoding="utf-8", newline="\n")
    payload["file_path"] = side.name
    body = json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(
        wecom_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, body, "")
    )
    monkeypatch.chdir(tmp_path)
    adapter = WeComAdapter()
    doc = adapter.read_document(f"kgent://wecom/{DOC_ID}")
    assert "第二段 ❤️" in doc.content
    assert doc.metadata.version == GET_VERSION


def test_search_hits_canonical_uri_and_node_type(monkeypatch):
    fake = _FakeWeCom()
    monkeypatch.setattr(wecom_mod, "run_cli", fake)
    adapter = WeComAdapter()
    hits = adapter.search_by_keywords("kgent-phase3-probe")
    assert hits, "fixture 应至少一条 hit"
    for hit in hits:
        assert hit.doc_uri.startswith("kgent://wecom/")
        assert hit.node_type == "doc"  # 词表保真：wecom 无 wiki_node，绝不虚构
    sent = fake.calls[0]
    body = json.loads(sent[sent.index("--json") + 1])
    assert body["keywords"] == ["kgent-phase3-probe"]
    assert body["search_scope"] == "title_content"
    assert body["limit"] == 10


def test_win32_cmd_resolution(monkeypatch):
    monkeypatch.setattr(wecom_mod.sys, "platform", "win32")
    assert WeComAdapter().cmd[0].endswith(".cmd")
    monkeypatch.setattr(wecom_mod.sys, "platform", "linux")
    assert WeComAdapter().cmd[0] == "wecom-cli"


def test_exit0_malformed_json_raises(monkeypatch):
    monkeypatch.setattr(wecom_mod, "run_cli", lambda argv, timeout, **kw: SubprocessResult(0, "not json", ""))
    with pytest.raises(AdapterError):
        WeComAdapter().read_document("kgent://wecom/X")


def test_exit0_error_envelope_raises(monkeypatch):
    """退出 0 但负载是错误档（code 893xxx 族）→ AdapterError，不静默成功。"""
    monkeypatch.setattr(
        wecom_mod, "run_cli",
        lambda argv, timeout, **kw: SubprocessResult(0, '{"errcode": 893001, "msg": "doc not found"}', ""),
    )
    with pytest.raises(AdapterError):
        WeComAdapter().read_document("kgent://wecom/X")


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(
        wecom_mod, "run_cli",
        lambda argv, timeout, **kw: SubprocessResult(2, "", "boom"),
    )
    with pytest.raises(AdapterError):
        WeComAdapter().read_document("kgent://wecom/X")
```

（fixture `doc-contents-get.json` 需同时含 `content` 与 `version` 键——长内容用例把 `content` 置 None、补 `file_path` 后即覆盖另一分支。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_wecom_adapter.py -v`
Expected: FAIL——现 WeComAdapter 走 wire-v1（`documents read <id> --json` 尾标形态），wecom-cli 不认 `documents` 服务。

- [ ] **Step 3: 实现（照 dingtalk.py 模式重写，完整代码）**

```python
"""WeCom adapter (§1.3): read lanes over ``wecom-cli`` (npm ``@wecom/cli``).

Deprecated (skills): 平台操作经 wecom-integration（ADR 0004）；CLI 面保留供
调试与 kgent hosted backend 车道。Phase 3 接真 wecom-cli 的**读**车道：

- :meth:`WeComAdapter.read_document` — ``doc contents get --json``；短内容
  内联 ``content``、长内容平台落盘 ``file_path``（cwd 相对——Fs 沙箱）读回；
  ``version`` → ``metadata.version``，是 ``kgent undo`` 补偿计划期的新鲜度
  数据源（B5：version 轴比对 + FM3 内容比对的输入，ledger.py 消费）。
- :meth:`WeComAdapter.search_by_keywords` — ``doc search --json``；hit 的
  ``node_type`` 一律 ``doc``（§7.2 词表无 wecom wiki_node——保真 = 不虚构；
  smartpage/sheet/smartsheet 的路由分流归 wecom-integration skill 的委派
  矩阵，按 ``doc_type``/URL ``<type>`` 段，不靠 node_type）。

写车道**不接**：create/update/delete 沿用 wire-v1 基类实现（未覆盖），一切
WeCom 写入经 wecom-integration skill（ADR 0004）——journal 台账（强制
--snapshot-content + version 双证）与快照写回补偿都活在 skill 侧；CLI 写
车道留给 kgent hosted backend 启用时再议（母 spec 非目标节）。

调用形态与 lark/dws 都不同：``wecom-cli <service> [resource...] <method>
--json '<JSON 参数>'``——``--json`` 是**输入体**旗标（argv 携带 JSON 文本，
``ensure_ascii=True`` 序列化保证纯 ASCII，规避 cmd 包装层的多字节陷阱），
非输出格式旗标；成功响应即 JSON 对象。错误契约：退出码 0/1/2 + 结构化
JSON 错误（``code`` 893000–893299 兜底 893999；envelope 键 ``errcode``/
``code`` 双认，锚点见 :func:`_extract_error_code`）。

Windows 解析：npm 全局安装的 wecom-cli 是 .cmd shim（三 shim 并存，
lark-cli.cmd/dws.cmd 同款教训）——默认 ``wecom-cli.cmd``（win32）／
``wecom-cli``（其余）。

**Payload 形状 provenance**：真机捕获前为 documented shape（wecom-cli
官方 skill 文档：search 外层 ``has_more/next_cursor/docs[]``、hit
``docid/doc_name/doc_type/url``；contents get 的 ``content``/``file_path``/
``version``）——字段路径集中在模块级 ``_extract_*`` 帮助函数：**键位对账
锚点，payload 真值回填时只改这里**（fixture 同步回填，见
``tests/fixtures/wecom-cli/FIXTURES-NOTE.md``）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from kgent.adapters.cli_adapter import CliCapabilityAdapter, run_cli
from kgent.errors import AdapterError
from kgent.types import Document, DocumentMetadata, FilterSpec, SearchResult

__all__ = ["WeComAdapter"]

#: ``doc search`` 的 ``limit`` 上限未文档化（官方示例用 10）——读车道按官方
#: 示例值封顶，更大 top_k 由 skill 车道翻页（``next_cursor``）解决。
_WECOM_SEARCH_LIMIT_DEFAULT = 10


def _extract_document(payload: dict[str, Any]) -> dict[str, Any]:
    """``doc contents get`` 的目标块。锚点：envelope 是否 ``data`` 包裹是
    FIXTURES-NOTE 冲突点 1——双层兜底，真值回填只改这里。"""
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _extract_hits(payload: dict[str, Any]) -> list[Any]:
    """``doc search`` 命中列表（官方 skill 文档：``docs[]``）。锚点同上。"""
    docs = payload.get("docs")
    if isinstance(docs, list):
        return docs
    items = payload.get("items")  # 兜底容器键（dws 同族命名）
    return items if isinstance(items, list) else []


def _extract_docid(item: dict[str, Any]) -> str:
    """稳定文档 ID（官方 skill 文档：``docid``；「docid 仅 cli 使用」）。锚点。"""
    for key in ("docid", "docId", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_title(item: dict[str, Any]) -> str:
    """文档名（search hit ``doc_name``；get ``name``）。锚点。"""
    for key in ("doc_name", "name", "title"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return ""


def _extract_content(data: dict[str, Any]) -> str | None:
    """正文（短内容内联 ``content``；``None``/缺失 → 走 file_path 通道）。锚点。"""
    value = data.get("content")
    return str(value) if value is not None else None


def _extract_content_file(data: dict[str, Any]) -> str | None:
    """长内容的平台落盘路径（cwd 相对——Fs 沙箱；adapter 进程 cwd 即 CLI cwd）。
    锚点。"""
    value = data.get("file_path")
    return str(value) if isinstance(value, str) and value else None


def _extract_version(data: dict[str, Any]) -> str | None:
    """文档 ``version``（B5 新鲜度轴；wecom 写命令返回空对象——version 只能
    从读取得，CLI 输出按未验证输入处理原样字符串化）。锚点。"""
    value = data.get("version")
    return str(value) if value is not None else None


def _extract_snippet(item: dict[str, Any]) -> str | None:
    """hit 摘要（``text_highlight``，官方 skill 文档）。锚点。"""
    for key in ("text_highlight", "snippet"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_error_code(payload: dict[str, Any]) -> int | None:
    """错误档的 code（893000–893299 兜底 893999；envelope 键 ``errcode``/
    ``code`` 双认——FIXTURES-NOTE 冲突点 3）。锚点。"""
    for key in ("errcode", "code"):
        value = payload.get(key)
        if isinstance(value, int) and value != 0:
            return value
    return None


def _node_type_from_hit(item: dict[str, Any]) -> str:
    """Server-fact 节点类型，值域只有 ``doc``|``wiki_node``（§7.2 词表）。

    WeCom 无 wiki/knowledge-space 概念 → 一律 ``doc``，绝不虚构
    ``wiki_node``（dingtalk 非文字产品落 doc 的同款纪律）。smartpage/sheet/
    smartsheet 的分流是 wecom-integration skill 委派矩阵的职责（消费
    ``doc_type`` 字段与 URL ``<type>`` 段），不经 node_type。
    """
    return "doc"


class WeComAdapter(CliCapabilityAdapter):
    """WeCom documents adapter — read lanes over ``wecom-cli``, writes via skill.

    读车道接真 wecom-cli（``doc contents get`` / ``doc search``，见模块
    docstring）；create/update/delete/archive/check_version 等**不接**——沿用
    wire-v1 基类实现仅用于测试替身与 hosted backend 车道，一切真实写入经
    wecom-integration skill（ADR 0004）。
    """

    def __init__(self, cmd: list[str] | None = None, timeout: float = 30.0) -> None:
        # On Windows, use wecom-cli.cmd for subprocess compatibility (npm shim)
        if cmd is None:
            cmd = ["wecom-cli.cmd" if sys.platform == "win32" else "wecom-cli"]
        super().__init__(cmd, "wecom", timeout)

    def _run_wecom(self, service_args: list[str], body: dict[str, Any]) -> dict[str, Any]:
        """Run ``self.cmd + service_args + ["--json", <body>]`` and decode one JSON object.

        ``--json`` 是输入体旗标（模块 docstring）：body 经 ``ensure_ascii=True``
        序列化为纯 ASCII argv 元素（cmd.exe 包装层对多字节 argv 的 first-block
        教训；docid/limit 等值本就 ASCII）。错误规范化与 wire-v1 ``_run`` 对齐：
        非零退出 → ``normalize_error``；退出 0 但非 JSON/非对象/错误档 code →
        :class:`AdapterError`（退出码为零不能替代业务证据——dws contracts 同款）。
        速率退避不在此层（skill 车道纪律，见 wecom-integration SKILL.md）。
        """
        argv = self.cmd + service_args + ["--json", json.dumps(body, ensure_ascii=True)]
        self._check_argv(argv)
        result = run_cli(argv, timeout=self.timeout)
        if result.returncode != 0:
            raise self.normalize_error(result.returncode, result.stderr)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"adapter {self.name!r}: CLI exited 0 with malformed JSON stdout: "
                f"{result.stdout[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise AdapterError(
                f"adapter {self.name!r}: CLI exited 0 with non-object JSON: {result.stdout[:200]!r}"
            )
        code = _extract_error_code(payload)
        if code is not None:
            raise AdapterError(
                f"adapter {self.name!r}: CLI reported error on exit 0 "
                f"(code {code}): {payload.get('msg') or payload.get('message') or payload}"
            )
        return payload

    def read_document(self, doc_uri: str) -> Document:
        """Deprecated (skills): 平台操作经 wecom-integration（ADR 0004）；CLI 面保留供调试与 kgent hosted backend 车道。

        Read via ``wecom-cli doc contents get --json {"docid": <id>}``。短内容
        内联；长内容平台落盘 ``file_path``（cwd 相对）读回。``version`` →
        ``metadata.version``（B5 新鲜度轴；缺失为 ``None`` → undo 计划落
        FM3 内容比对路径）。
        """
        native_id = self._native_id(doc_uri)
        payload = self._run_wecom(["doc", "contents", "get"], {"docid": native_id})
        data = _extract_document(payload)
        title = _extract_title(data)
        content = _extract_content(data)
        if content is None:
            side = _extract_content_file(data)
            if side is None:
                raise AdapterError(
                    f"adapter {self.name!r}: contents get returned neither content "
                    f"nor file_path: {json.dumps(payload, ensure_ascii=False)[:200]!r}"
                )
            try:
                content = Path(side).read_text(encoding="utf-8")
            except OSError as exc:
                raise AdapterError(
                    f"adapter {self.name!r}: long-content file unreadable "
                    f"({side!r}, cwd-relative Fs sandbox): {exc}"
                ) from exc
        meta = DocumentMetadata(
            doc_uri=doc_uri,
            title=title,
            backend=self.name,
            version=_extract_version(data),
            node_type=_node_type_from_hit(data),
        )
        return Document(doc_uri=doc_uri, title=title, content=content, metadata=meta)

    def search_by_keywords(
        self,
        query: str,
        filters: FilterSpec | None = None,
        top_k: int = 10,
        fields: list[str] | None = None,
    ) -> list[SearchResult]:
        """Deprecated (skills): 平台操作经 wecom-integration（ADR 0004）；CLI 面保留供调试与 kgent hosted backend 车道。

        Search via ``wecom-cli doc search --json {"keywords": [<q>], ...}``
        （官方示例的调用形状）；hit 类型经 :func:`_node_type_from_hit`（一律
        ``doc``，词表保真）。``filters``/``fields`` 本车道未消费（doc_types/
        creator 等过滤旗标归 skill 车道按需展开）。
        """
        limit = min(top_k, _WECOM_SEARCH_LIMIT_DEFAULT)
        payload = self._run_wecom(
            ["doc", "search"],
            {"keywords": [query], "search_scope": "title_content", "limit": limit},
        )
        results: list[SearchResult] = []
        for item in _extract_hits(payload):
            if not isinstance(item, dict):
                continue
            native_id = _extract_docid(item)
            if not native_id:
                continue  # 无稳定 ID 的 hit 不进结果（docid 是唯一稳定身份）
            uri = self._canonical(native_id)
            title = _extract_title(item)
            snippet = _extract_snippet(item)
            node_type = _node_type_from_hit(item)
            meta = DocumentMetadata(
                doc_uri=uri,
                title=title,
                backend=self.name,
                node_type=node_type,
            )
            results.append(
                SearchResult(
                    doc_uri=uri,
                    metadata=meta,
                    rank=0,  # wecom hit 无 rank 字段（doc_type/highlight 族）
                    snippet=snippet,
                    mode_used="keyword",
                    node_type=node_type,
                )
            )
        return results[:top_k]
```

**对账步骤**：实现后对照 `tests/fixtures/wecom-cli/*.json` 逐键核对——捕获件与代码键位不符时，以捕获件为准改 `_extract_*` 锚点，测试期望值不动。`test_adapters.py` 若构造了 `WeComAdapter`（S65 矩阵有 wecom 参数化用例走 wire-v1 fake）——先读再动：**禁止改断言语义**，只允许适配构造签名这类机械跟随；fake `tests/fakes/fake_cli.py` 的 wecom wire 车道（`documents` 域）保持原样服务既有用例。

- [ ] **Step 4: 跑测试确认通过 + 全套无新增失败**

Run: `python -m pytest tests/test_wecom_adapter.py tests/test_adapters.py -v && python -m pytest tests -q 2>&1 | tail -3`
Expected: 新测试 PASS；全套失败数 ≤ baseline（adapter registry 单例的默认 cmd 在 win32 变为 `wecom-cli.cmd`——`test_adapters.py` 的 wecom 用例若走 fake `run_cli` 注入则不受影响；若有真 spawn 断言，按实测修正测试夹具路径而非断言）。

- [ ] **Step 5: ruff format 债清零（本 PR 新增文件）+ Commit**

```bash
ruff format tests/test_wecom_adapter.py src/kgent/adapters/wecom.py   # 新增/重写文件必须 clean（Phase 2 Task 7 教训）
git add src/kgent/adapters/wecom.py tests/test_wecom_adapter.py
git commit -m "feat(adapters): WeComAdapter 接真 wecom-cli——undo 新鲜度读（version/FM3）+ search 类型保真（B11-wecom）"
```

---

### Task 4: agent evals runner 放行 wecom-cli + evals fixtures wecom 腿

**Files:**
- Modify: `tools/run-agent-evals.py:186-187`（allowedTools 追加 `Bash(wecom-cli:*)`；grader 三平台兜底正则 `(?:lark|dingtalk|wecom)-integration` Phase 2 Task 4 已覆盖 wecom——**勿重复改**）
- Modify: `evals/skills/knowledge-storage-evals.json`（新增 id10 wecom 目标条目）
- Modify: `evals/skills/wiki-setup-evals.json`（id3 补三平台委派行）
- Modify: `evals/README.md:46-47`（wecom 低分预期段落退役）
- Test: `tests/test_agent_evals_runner.py`（Modify——追加 1 条）

**Interfaces:**
- Consumes: Task 2 的 `skills/wecom-integration/SKILL.md`（委派断言的词面来源）
- Produces: wecom 目标的 eval 走 wecom-integration 委派断言；agent evals 的 wecom 腿在 headless claude 里可真实调用 wecom-cli（allowedTools 放行）

- [ ] **Step 1: 写失败测试（先改测试）**

`tests/test_agent_evals_runner.py` 追加：

```python
def test_runner_allows_wecom_cli():
    """Phase 3 接线：allowedTools 必须放行 wecom-cli——wecom 腿的 eval 会真实
    调平台 CLI，缺放行 = 权限拒绝失败，失败形态不是断言未命中而是工具被拦，
    报告里看不出来龙去脉。源码文本级钉住（claude() 是嵌套函数，无纯函数面）。"""
    source = (REPO / "tools" / "run-agent-evals.py").read_text(encoding="utf-8")
    assert '"Bash(wecom-cli:*)"' in source
```

（grader 的 wecom 词面已由 Phase 2 覆盖——用一条直接断言复核，不重写已有用例：）

```python
def test_grader_accepts_wecom_integration_wording():
    passed, misses, manual = runner.heuristic_grade(
        ["For WeCom targets the skill delegates execution via wecom-integration, not 'kgent update'"],
        "transcript ... wecom-integration ... 委派了",
    )
    assert passed == 1 and not misses and not manual
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_agent_evals_runner.py -v`
Expected: `test_runner_allows_wecom_cli` FAIL（allowedTools 尚无 wecom-cli）；`test_grader_accepts_wecom...` PASS（Phase 2 已覆盖——若 FAIL 说明 runner 被改回，查明再动）。

- [ ] **Step 3: 修 runner（一行）**

```python
            argv += ["--allowedTools", "Bash(kgent:*)", "Bash(lark-cli:*)", "Bash(dws:*)",
                     "Bash(wecom-cli:*)", "Bash(dir:*)", "Read", "Write", "Edit"]
```

- [ ] **Step 4: evals fixtures wecom 腿**

原始形态核查结论（`git show 3da94c7:evals/skills/...`）：**无可恢复的 wecom 写目标腿**——wiki-setup id3 的 prompt 自始含 WeCom（三后端 fan-out），knowledge-storage 无 wecom 目标条目；故按现有纪律断言风格新写：

`evals/skills/knowledge-storage-evals.json` 在 id9 之后追加：

```json
    {
      "id": 10,
      "prompt": "Save this to WeCom please: 'Customer escalation hotline is +86-400-123-4567, staffed 9:00-18:00 CST. Escalate SEV1 incidents within 15 minutes.'",
      "expected_output": "The skill should target wecom (explicit user input), search for existing content via wecom-integration, and propose create or update accordingly. Must show provenance noting 'explicit user input' as the backend source.",
      "files": [],
      "expectations": [
        "The skill targets wecom backend (explicit user input overrides any defaults)",
        "The provenance records target source as 'explicit user input'",
        "The skill searches wecom for existing content before proposing",
        "A proposal is shown before any write",
        "The confirmation includes the native WeCom doc URL from the platform response, not kgent://wecom/...",
        "The content is formatted as markdown, not raw text",
        "The skill runs 'kgent route --dry-run' before executing any write",
        "The skill wraps the write with 'kgent journal begin' and 'kgent journal end'",
        "For WeCom targets the skill delegates execution via wecom-integration, not 'kgent update'"
      ]
    }
```

`evals/skills/wiki-setup-evals.json` id3 的 expectations 在 `"Each backend is attempted independent"` 行后插入（原 7 条不动）：

```json
        "Each leg executes through its platform's integration skill (lark via lark-integration, dingtalk via dingtalk-integration, wecom via wecom-integration)",
```

`evals/README.md:46-47` 原文：

```markdown
- wecom 相关 eval 在 Phase 3（wecom-integration）落地前会低分——属预期而
  非回归；DingTalk eval 自 Phase 2 起按正常门槛验收。
```

替换为：

```markdown
- DingTalk eval 自 Phase 2、WeCom eval 自 Phase 3 起按正常门槛验收；低分时
  先核 fixture 前提（租户漂移）再怀疑行为——wecom 腿凭据未就绪时按 EVIDENCE
  声明 skipped，不硬跑。
```

- [ ] **Step 5: 校验 + Commit**

Run: `python -m pytest tests/test_agent_evals_runner.py -v && python tools/run-agent-evals.py | head -30`
Expected: 测试 PASS；dry 计划列出 25 条 eval（24 + knowledge-storage-10）、无 JSON 解析错误。

```bash
git add tools/run-agent-evals.py evals/skills/knowledge-storage-evals.json evals/skills/wiki-setup-evals.json evals/README.md tests/test_agent_evals_runner.py
git commit -m "test(evals): wecom 腿接线——runner 放行 wecom-cli + knowledge-storage id10 + wiki-setup id3 委派行（Phase 3）"
```

---
### Task 5: B5/B8 真机 e2e（wecom 快照写回闭环 + FM2/FM3 拒绝变体 + 内容完整性）

**Files:**
- Test: `tests/e2e/test_wecom_undo_real.py`（Create；结构沿用 `tests/e2e/test_dingtalk_undo_real.py` 的全部修正：`sys.executable -m kgent`、kgent `--json` 叶子位、win32 `.cmd` 解析、`except BaseException` 前缀保护 + 幂等 `_teardown`、session 末 leftover 重试点名、UTF-8 stdio、有界轮询、常量区集中命令真值）

**Interfaces:**
- Consumes: Task 1 命令真值表（PROBE-NOTES）+ version 轴定谳；Task 3 WeComAdapter（undo 计划期新鲜度读经 registry 单例）；台账 journal begin/end 既有 CLI（`--snapshot-content`/`--revision-before`/`--revision-after`）
- Produces: B5（快照写回闭环 + FM2 version 轴拒绝 + FM3 无证据拒绝）与 B8（多段中文+emoji 完整性，FM7 回归装甲）的真机证据；`_wecom_cmd()` 可复用解析

- [ ] **Step 1: 写 e2e（真机标记 + skipif 凭据门；全文如下）**

```python
"""B5/B8 真机：wecom 探针文档 undo 计划 → 快照写回闭环。

ADR 0004/0005 的 wecom 侧真机验收载体：kgent 台账 begin/end → ``kgent undo``
只产补偿计划（mechanism=snapshot-restore、history_hint=None、
integration_skill=wecom-integration——wecom 无平台 history，快照写回是唯一
选项），执行归 wecom-integration skill——本测试扮演该 skill：把
``plan.plan.snapshot``（begin ``--snapshot-content`` 落盘的写前全文）经
``doc contents overwrite`` 的 file_path 通道写回并读回断言还原（B5）。
另以多段中文 + emoji 内容的写入/读回全量保真压 first-block 事故回归
（B8/FM7），以写后第三方编辑验证 version 轴拒绝（FM2），以无 version 证据
的 op 验证 FM3 内容比对拒绝（fail closed）。

新鲜度设计裁决（见 Phase 3 计划「设计裁决」节）：wecom 写命令返回空对象，
version 证据只能来自读——journal end 必须带 ``--revision-after``（写后
``doc contents get`` 的 version），否则 undo 走 FM3 快照内容比对而对已变
更内容必然拒绝（lark e2e docstring 修正 3 的同款教训，wecom 专属路径）。

**凭据门**：wecom-cli 未装或 ``wecom-cli auth show --status`` 非
``authorized`` 时整文件 skip（bot-only 身份，auth init 需维护者本人扫码）。
命令拼写真值：``tests/fixtures/wecom-cli/PROBE-NOTES.md``；payload 键位
PENDING 项：同目录 ``FIXTURES-NOTE.md``。

与 Phase 2 e2e 纪法的真机修正/契约（沿用 test_dingtalk_undo_real.py）：
1. ``kgent`` 经 ``sys.executable -m kgent``（或 ``KGENT_BIN``）解析——PATH 上
   是旧安装，必须打仓库源码。
2. kgent 的 ``--json`` 放叶子子命令末尾（argparse 子解析器独立 namespace）。
3. ``wecom-cli`` 在 Windows 解析 ``wecom-cli.cmd``（npm 三 shim；
   ``shell=False`` 不自动补 .cmd）。``--json`` 是 wecom-cli 的**输入体**旗标，
   不承担输出格式——输出默认 JSON（PROBE-NOTES 定谳项）。
4. 内容通道：多行/含 CJK 一律 ``file_path``（cwd 相对，Fs 沙箱）——
   ``overwrite`` 的 JSON 体 ``content`` XOR ``file_path``；台账快照在
   ``~/.kgent/journal/snapshots/``，写回前必须先拷进 cwd。
5. **teardown 无删除命令**：wecom 平台无文档删除 API（PROBE-NOTES 定谳）→
   rename 隔离（``kgent-phase3-probe-DELETE-ME-`` 前缀）+ session 末重试 +
   leftover 点名（docid + URL + 人工清理 runbook）。
6. 异步：``doc import`` 的 ``task_status`` 与 overwrite 的读回可见性都可能
   滞后 → 有界轮询（lark/dws 版 ``_poll_content`` 同款）。
7. version 轴探针门控：本文件的 happy path 断言 V1 < V2（写推动 version
   递增）——若平台 version 不递增，测试按失败处理并上报（设计裁决第 4 条：
   ledger 语义级缺口，需控制器裁决，不静默绕过）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.real]

#: 仓库无 pytest marker 注册表：``e2e``/``real`` 直接打标，靠 skipif 做真机门。

# ---------------------------------------------------------------------------
# 可调常量区 —— wecom-cli 命令真值（PROBE-NOTES；真值漂移只改本区）
# ---------------------------------------------------------------------------

PROBE_TITLE = "kgent-phase3-probe-临时"
#: B8 用独立标题：人工清理时能与 B5 探针区分。
PROBE_TITLE_B8 = "kgent-phase3-probe-完整性"
#: teardown 隔离前缀（平台无删除命令——模块 docstring 修正 5）。
DELETE_ME_PREFIX = "kgent-phase3-probe-DELETE-ME-"

CONTENT_A = "AAA-CONTENT"
CONTENT_B = "BBB-CONTENT"
CONTENT_C = "CCC-CONTENT"
#: B8：多段中文 + emoji + 中文标点——first-block 事故回归装甲（FM7）
CONTENT_B8 = (
    "# Phase 3 完整性探针\n\n"
    "第一段中文内容，包含「中文标点」。\n\n"
    "第二段含 emoji ❤️🎉 与多行\n换行内容。\n"
)

#: 探针生命周期命令（官方 skill 文档证实 + PROBE-NOTES [help 实测] 对账）
CMD_DOC_IMPORT = ("doc", "import")            # --json {"doc_type","file_name","file_path","passwd"?}
CMD_CONTENTS_GET = ("doc", "contents", "get")  # --json {"docid"}
CMD_CONTENTS_OVERWRITE = ("doc", "contents", "overwrite")  # --json {"docid","content_type","content"|"file_path"}
CMD_DOC_SEARCH = ("doc", "search")             # --json {"keywords","search_scope","limit"}
CMD_NAMES_UPDATE = ("doc", "names", "update")  # --json {"docid","new_name"}（teardown 隔离）

DOC_TYPE_DOC = "doc"        # ⚠ import 的 doc_type 枚举按 PROBE-NOTES 真值
CONTENT_TYPE_TEXT = "text"  # overwrite 的 content_type（补偿写回用纯文本）

#: 有界轮询预算（import 异步建档 / overwrite 读回可见性——修正 6）
_IMPORT_POLL_ROUNDS = 12
_IMPORT_POLL_INTERVAL_SECONDS = 5
_READBACK_POLL_ROUNDS = 6
_READBACK_POLL_INTERVAL_SECONDS = 2

WECOM_TIMEOUT_SECONDS = 120
KGENT_TIMEOUT_SECONDS = 120

#: teardown 隔离失败的探针 docid（session 末重试 + 人工清理提示）
_leftover_probes: list[str] = []
#: 已隔离成功的探针 docid（``_teardown`` 幂等短路）
_quarantined_probes: set[str] = set()


# ---------------------------------------------------------------------------
# 进程封装
# ---------------------------------------------------------------------------


def _utf8_stdio() -> None:
    """CJK/emoji evidence 打印在 Windows 控制台缺省编码下会炸——统一 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


_utf8_stdio()


def _kgent() -> list[str]:
    """仓库源码的 kgent 调用形态（修正 1）。"""
    override = os.environ.get("KGENT_BIN")
    if override:
        return [override]
    return [sys.executable, "-m", "kgent"]


def _wecom_cmd() -> list[str]:
    """wecom-cli 的可执行形态：Windows 上解析 ``wecom-cli.cmd``（修正 3）。

    与 :class:`kgent.adapters.wecom.WeComAdapter` 同一规则；``shutil.which``
    返回完整路径（规避无扩展名 sh shim 的 bash 语义误用）。
    """
    override = os.environ.get("WECOM_CLI_BIN")
    if override:
        return [override]
    resolved = shutil.which("wecom-cli.cmd") if sys.platform == "win32" else None
    if resolved is None:
        resolved = shutil.which("wecom-cli")
    return [resolved] if resolved else ["wecom-cli"]


def _wecom(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    timeout: int = WECOM_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """跑一条 wecom-cli 命令并解析 JSON 输出（输出默认 JSON——PROBE-NOTES 定谳）。

    失败判定：非零退出 / 非 JSON / 非 dict / 错误档 code（``errcode``/``code``
    非 0，893xxx 族）。``check=True`` → AssertionError 带 stdout/stderr 尾部；
    ``check=False``（teardown/探测）→ 打印并返回 ``None``。``cwd`` 锚定
    file_path 的 Fs 沙箱语义。stdin=DEVNULL：任何等待输入都立即 EOF。
    """
    argv = [*_wecom_cmd(), *args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if check:
            raise AssertionError(f"wecom-cli {' '.join(args)} could not run: {exc}") from exc
        print(f"wecom-cli {' '.join(args)} could not run: {exc}")
        return None
    payload: dict[str, Any] | None = None
    try:
        decoded = json.loads(proc.stdout)
        payload = decoded if isinstance(decoded, dict) else None
    except ValueError:
        payload = None
    failed = (
        proc.returncode != 0
        or payload is None
        or any(isinstance(payload.get(k), int) and payload[k] != 0 for k in ("errcode", "code"))
    )
    if check:
        assert not failed, (
            f"wecom-cli {' '.join(args)} failed:\n"
            f"  rc={proc.returncode}\n"
            f"  stdout={proc.stdout[-800:]}\n"
            f"  stderr={proc.stderr[-800:]}"
        )
        return payload
    if failed:
        print(
            f"wecom-cli {' '.join(args)} failed (rc={proc.returncode}): "
            f"stdout={proc.stdout[-400:]!r} stderr={proc.stderr[-400:]!r}"
        )
        return None
    return payload


def _wecom_json(service_args: tuple[str, ...], body: dict[str, Any], **kw: Any) -> dict[str, Any] | None:
    """``--json`` 输入体形态的封装：argv = [*service_args, "--json", <body>]。"""
    return _wecom(*service_args, "--json", json.dumps(body, ensure_ascii=True), **kw)


def _kgent_json(command: str, *rest: str) -> dict[str, Any]:
    """kgent 的 ``--json`` 放整条子命令路径末尾（修正 2）。"""
    out = subprocess.run(
        [*_kgent(), command, *rest, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=KGENT_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if out.returncode != 0:
        raise AssertionError(
            f"kgent {command} {' '.join(rest)} failed:\n"
            f"  rc={out.returncode}\n  stdout={out.stdout[-800:]}\n  stderr={out.stderr[-800:]}"
        )
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise AssertionError(
            f"kgent {command} printed non-JSON stdout: {out.stdout[:400]!r}"
        ) from exc


# ---------------------------------------------------------------------------
# payload 键位对账锚点（候选键容错；取不到打印原 payload 供补捕定谳）
# ---------------------------------------------------------------------------


def _extract_docid(payload: dict[str, Any]) -> str:
    """import / get / search 响应里的 docid（官方 skill 文档点名 ``docid``）。"""
    block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    for source in (block, payload):
        for key in ("docid", "docId", "id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    raise AssertionError(
        "response has no docid under known keys (docid/docId/id) — capture the "
        "payload and pin the anchor (tests/fixtures/wecom-cli/FIXTURES-NOTE.md): "
        f"{json.dumps(payload, ensure_ascii=False)[:800]}"
    )


def _probe_url(payload: dict[str, Any]) -> str:
    """探针的原生 URL（响应 ``url``——scode 签名原样保留，供人工清理）。"""
    block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    value = block.get("url") or payload.get("url")
    return str(value) if value else "<no url in response>"


def _extract_version_int(payload: dict[str, Any]) -> int | None:
    """``doc contents get`` 的 version（int 化；非数值返回 None——调用方停并上报）。"""
    block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    value = block.get("version")
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    print(f"[version-axis] non-numeric version {value!r} — see plan design ruling #4")
    return None


def _extract_content(payload: dict[str, Any]) -> str:
    """``doc contents get`` 的正文：短内联 ``content``；长内容 ``file_path`` 读回。"""
    block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    value = block.get("content")
    if value is not None:
        return str(value)
    side = block.get("file_path")
    if isinstance(side, str) and side:
        return Path(side).read_text(encoding="utf-8")
    raise AssertionError(
        "contents get returned neither content nor file_path — capture the payload "
        f"and pin the anchor: {json.dumps(payload, ensure_ascii=False)[:800]}"
    )


# ---------------------------------------------------------------------------
# 探针内容 / 生命周期
# ---------------------------------------------------------------------------


def _write_text(tmp_dir: Path, name: str, text: str) -> str:
    """内容落 cwd 相对文件（file_path 通道 + LF 纪律——B8 换行保真断言依赖）。"""
    path = tmp_dir / name
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return name


def _write_probe_docx(tmp_dir: Path, name: str, text: str) -> str:
    """最小 .docx（stdlib zipfile——零新依赖）供 ``doc import`` 建探针在线文档。

    wecomcli-doc 的 create 是两步流：本地生成 .docx → import 为在线文档
    （返回 docid/url/task_status）。最小 OOXML 三件套即导入为单段文档。
    """
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>"
        + escape(text)
        + "</w:t></w:r></w:p></w:body></w:document>"
    )
    path = tmp_dir / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return name


def _create_probe(tmp_path: Path, title: str, content: str) -> tuple[str, str]:
    """建探针在线文档（import 两步流）→ ``(docid, url)``；轮询到内容可见。

    import 的 task_status 异步（修正 6）——轮询 ``doc contents get`` 直到正文
    出现（有界），耗尽按失败处理（teardown 保证覆盖其后一切前缀）。
    """
    rel = _write_probe_docx(tmp_path, "probe.docx", content)
    imported = _wecom_json(
        CMD_DOC_IMPORT,
        {"doc_type": DOC_TYPE_DOC, "file_name": f"{title}.docx", "file_path": rel},
        cwd=tmp_path,
    )
    # import 响应的 docid 键位是 envelope 冲突点——取不到时用 search 兜底定位探针
    docid: str | None = None
    try:
        docid = _extract_docid(imported or {})
    except AssertionError:
        docid = None
    for _ in range(_IMPORT_POLL_ROUNDS):
        if docid:
            break
        found = _wecom_json(
            CMD_DOC_SEARCH,
            {"keywords": [title], "search_scope": "title_content", "limit": 10},
            check=False,
        )
        docs = (found or {}).get("docs") or []
        for hit in docs:
            if isinstance(hit, dict) and title in str(hit.get("doc_name", "")):
                docid = _extract_docid(hit)
                break
        if not docid:
            time.sleep(_IMPORT_POLL_INTERVAL_SECONDS)
    assert docid, (
        f"probe doc {title!r} never became searchable within "
        f"{_IMPORT_POLL_ROUNDS * _IMPORT_POLL_INTERVAL_SECONDS}s"
    )
    got: dict[str, Any] = {}
    for _ in range(_IMPORT_POLL_ROUNDS):
        got = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path) or {}
        if content in _extract_content(got):
            return docid, _probe_url(got)
        time.sleep(_IMPORT_POLL_INTERVAL_SECONDS)
    raise AssertionError(
        f"imported probe content {content!r} not visible within "
        f"{_IMPORT_POLL_ROUNDS * _IMPORT_POLL_INTERVAL_SECONDS}s: "
        f"{json.dumps(got, ensure_ascii=False)[:600]}"
    )


def _quarantine_probe(docid: str) -> bool:
    """teardown：rename 隔离（平台无删除命令——模块 docstring 修正 5）。"""
    renamed = _wecom_json(
        CMD_NAMES_UPDATE,
        {"docid": docid, "new_name": f"{DELETE_ME_PREFIX}{docid}"},
        check=False,
    )
    return renamed is not None


def _teardown(docid: str) -> None:
    """``finally`` 必隔离；失败把 docid 点名 + session 末重试。

    幂等：``_journaled_overwrite`` 在 docid 到手后自带 except-teardown，
    调用方的 ``finally`` 会再调一次——已隔离就直接短路。
    """
    if docid in _quarantined_probes:
        return
    if _quarantine_probe(docid):
        _quarantined_probes.add(docid)
        if docid in _leftover_probes:
            _leftover_probes.remove(docid)
        return
    if docid not in _leftover_probes:
        _leftover_probes.append(docid)
    print(
        f"TEARDOWN FAILED: probe doc {docid} not quarantined - rename manually: "
        f"wecom-cli doc names update --json "
        f"'{{\"docid\":\"{docid}\",\"new_name\":\"{DELETE_ME_PREFIX}{docid}\"}}', "
        "then delete it in the WeCom client (no CLI delete exists)"
    )


def _journaled_overwrite(tmp_path: Path, *, record_revision_after: bool = True) -> tuple[str, str, int, int]:
    """B5 公共前缀：建探针（A）→ 读 V1 → journal begin（快照 A + rev V1）
    → overwrite（B，file_path 通道）→ 读 V2 → journal end。

    返回 ``(docid, op_id, v1, v2)``。``record_revision_after=False`` 是 FM3
    变体（end 不带 version 证据——计划必走快照内容比对路径）。teardown 保证
    覆盖 create 之后的全部前缀。
    """
    docid, _url = _create_probe(tmp_path, PROBE_TITLE, CONTENT_A)
    try:
        got = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path)
        v1 = _extract_version_int(got)
        assert v1 is not None, (
            "no numeric version from doc contents get — version axis unavailable, "
            "see plan design ruling #4 (escalate, do not improvise)"
        )

        begin = _kgent_json(
            "journal",
            "begin",
            "--operation",
            "update",
            "--backend",
            "wecom",
            "--doc-uri",
            f"kgent://wecom/{docid}",
            "--revision-before",
            str(v1),
            "--snapshot-content",
            CONTENT_A,
        )
        op_id = begin["entry"]["op_id"]

        rel = _write_text(tmp_path, "probe-after.md", CONTENT_B)
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        after = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path)
        v2 = _extract_version_int(after)
        assert v2 is not None, "no numeric version after overwrite — escalate (ruling #4)"
        assert v2 > v1, (
            f"version did not advance on the journaled write: v1={v1} v2={v2} — "
            "version axis is not a per-edit counter, see plan design ruling #4"
        )

        end_args = ["journal", "end", "--op-id", op_id, "--status", "ok"]
        if record_revision_after:
            end_args += ["--revision-after", str(v2)]
        end = _kgent_json(*end_args)
        assert end["entry"]["status"] == "ok"
    except BaseException:
        # 断言/KeyboardInterrupt/SystemExit 一视同仁：探针不留给真机租户。
        _teardown(docid)
        raise
    print(f"[kgent-phase3-probe] v1={v1} v2={v2} docid={docid}")
    return docid, op_id, v1, v2


def _poll_content(docid: str, needle: str, cwd: Path) -> dict[str, Any]:
    """overwrite 读回可见性可能滞后：轮询直到包含目标内容（或轮询耗尽）。"""
    last: dict[str, Any] = {}
    for _ in range(_READBACK_POLL_ROUNDS):
        last = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=cwd) or {}
        if needle in json.dumps(last, ensure_ascii=False):
            return last
        time.sleep(_READBACK_POLL_INTERVAL_SECONDS)
    return last


# ---------------------------------------------------------------------------
# 凭据门（模块级 skipif）
# ---------------------------------------------------------------------------


def _wecom_identity_available() -> bool:
    """wecom-cli 已装且已授权（``auth show --status`` → 单行 ``authorized``）。

    解析复用 :func:`_wecom_cmd`（含 ``WECOM_CLI_BIN`` override 与 win32
    ``.cmd`` 规则）——门与探针看到的必须是同一个二进制。解析落空/非零退出/
    输出不是 ``authorized`` 一律按「凭据不可用」处理（fail-closed；bot-only
    身份，auth init 需维护者本人扫码）。
    """
    cmd = _wecom_cmd()
    if not Path(cmd[0]).exists():
        return False
    try:
        out = subprocess.run(
            [*cmd, "auth", "show", "--status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and out.stdout.strip() == "authorized"


pytestmark.append(
    pytest.mark.skipif(
        not _wecom_identity_available(),
        reason=("real-machine probe: wecom-cli identity unavailable (credentials blocked, 见 EVIDENCE)"),
    )
)


# ---------------------------------------------------------------------------
# B8 —— 多段中文 + emoji 完整性（first-block 事故回归装甲，FM7）
# ---------------------------------------------------------------------------


def test_b8_content_integrity(tmp_path):
    """B8：多段中文 + emoji + 中文标点经 file_path 写入 → 读回全量保真。

    内容**不走 ``--json`` argv 内联**（多行/CJK 的 argv 内联正是 first-block
    事故通道）；断言覆盖标题块、中文标点、emoji（VS16 变体选择符）与块内换行。
    """
    docid, _url = _create_probe(tmp_path, PROBE_TITLE_B8, "seed")
    try:
        rel = _write_text(tmp_path, "probe-b8.md", CONTENT_B8)
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        got = _poll_content(docid, "❤️🎉", tmp_path)
        rendered = json.dumps(got, ensure_ascii=False)
        content = _extract_content(got)
        for needle in (
            "Phase 3 完整性探针",
            "第一段中文内容",
            "「中文标点」",
            "❤️🎉",
            "第二段含 emoji",
        ):
            assert needle in rendered, f"B8 content lost {needle!r}; fetched={rendered[:600]}"
        assert "❤️🎉" in content and "与多行\n换行内容" in content, (
            f"B8 content lost emoji/newline fidelity: content={content[:400]!r}"
        )
        print(f"[kgent-phase3-probe] B8 content_bytes={len(content.encode('utf-8'))}")
    finally:
        _teardown(docid)


# ---------------------------------------------------------------------------
# B5 —— undo 计划 → 快照写回闭环
# ---------------------------------------------------------------------------


def test_b5_undo_plan_and_snapshot_restore(tmp_path):
    """B5：undo 计划（snapshot-restore）→ integration skill 腿写回 → 读回还原。"""
    docid, op_id, v1, v2 = _journaled_overwrite(tmp_path)
    try:
        plan_json = _kgent_json("undo", op_id)
        print("undo plan:", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "ok"
        assert plan_json["mode"] == "plan"
        assert plan_json["integration_skill"] == "wecom-integration"
        assert plan_json["plan"]["mechanism"] == "snapshot-restore"
        assert plan_json["plan"]["history_hint"] is None  # wecom 无平台 history
        assert int(plan_json["plan"]["revision_before"]) == v1
        snapshot_path = Path(plan_json["plan"]["snapshot"])
        assert snapshot_path.read_text(encoding="utf-8") == CONTENT_A

        # TOCTOU 执行前复核（wecom-integration skill Undo 节步骤 3）：当前
        # version 必须仍 == plan.revision_current——绝不带着过期计划落写回。
        current = _wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path)
        v_now = _extract_version_int(current)
        assert v_now is not None, "TOCTOU recheck got no version"
        assert v_now == int(plan_json["plan"]["revision_current"]), (
            f"TOCTOU drift: fetched version {v_now} != plan "
            f"{plan_json['plan']['revision_current']}"
        )

        # 快照在 ~/.kgent/journal/snapshots/（Fs 沙箱外）——先拷进 cwd 再写回。
        rel = _write_text(tmp_path, "snapshot-restore.md", snapshot_path.read_text(encoding="utf-8"))
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        restored = _poll_content(docid, CONTENT_A, tmp_path)
        rendered = json.dumps(restored, ensure_ascii=False)
        assert CONTENT_A in rendered, (
            f"snapshot-restore did not restore {CONTENT_A!r} within "
            f"{_READBACK_POLL_ROUNDS * _READBACK_POLL_INTERVAL_SECONDS}s: {rendered[:600]}"
        )
        assert CONTENT_B not in rendered, "post-restore content still carries the undone write"
        print(
            f"[kgent-phase3-probe] B5 v1={v1} v2={v2} "
            f"final_version={_extract_version_int(restored)}"
        )
    finally:
        _teardown(docid)


def test_b5_fm2_rejects_after_concurrent_edit(tmp_path):
    """FM2：journal end 之后第三方再写 → version 轴不符 → undo 计划 rejected。

    计划期拒绝 = 不产生可执行补偿：mode 仍是 plan、status=rejected、reason
    带两侧 version——绝不规划一次盲回滚（ledger.compensation_plan 契约）。
    """
    docid, op_id, _v1, v2 = _journaled_overwrite(tmp_path)
    try:
        rel = _write_text(tmp_path, "probe-concurrent.md", CONTENT_C)
        _wecom_json(
            CMD_CONTENTS_OVERWRITE,
            {"docid": docid, "content_type": CONTENT_TYPE_TEXT, "file_path": rel},
            cwd=tmp_path,
        )
        v3 = _extract_version_int(_wecom_json(CMD_CONTENTS_GET, {"docid": docid}, cwd=tmp_path))
        assert v3 is not None and v3 > v2, (
            f"concurrent write did not advance version: v2={v2} v3={v3} — "
            "version axis unreliable, escalate (ruling #4)"
        )
        plan_json = _kgent_json("undo", op_id)
        print("undo plan (FM2):", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "rejected"
        assert plan_json["mode"] == "plan"
        reason = str(plan_json.get("reason", ""))
        assert f"expected revision {v2}" in reason, f"reason lacks journaled version: {reason!r}"
        assert f"current {v3}" in reason, f"reason lacks current version: {reason!r}"
    finally:
        _teardown(docid)


def test_b5_fm3_rejects_without_revision_evidence(tmp_path):
    """FM3：end 无 version 证据的 op → 快照内容比对 → 对已变更内容必然拒绝。

    这是 wecom 专属 fail-closed 路径的活体锚（设计裁决第 3 条）：无
    ``--revision-after`` 的 update，undo 唯一的新鲜度证据是「当前内容 ==
    写前快照」——写已变更内容 → 不符 → rejected，绝不盲回滚。
    """
    docid, op_id, _v1, _v2 = _journaled_overwrite(tmp_path, record_revision_after=False)
    try:
        plan_json = _kgent_json("undo", op_id)
        print("undo plan (FM3):", json.dumps(plan_json, ensure_ascii=False, indent=2))
        assert plan_json["status"] == "rejected"
        assert plan_json["plan"]["mechanism"] == "snapshot-restore"
        reason = str(plan_json.get("reason", ""))
        assert "snapshot no longer matches" in reason, (
            f"reason is not the FM3 content-comparison verdict: {reason!r}"
        )
    finally:
        _teardown(docid)


@pytest.fixture(scope="session", autouse=True)
def _retry_leftovers():
    """session 末对隔离失败的探针再改名一次，仍失败则点名人工清理。"""
    yield
    for docid in list(_leftover_probes):
        if _quarantine_probe(docid):
            _leftover_probes.remove(docid)
            print(f"probe doc {docid} quarantined on retry")
    for docid in _leftover_probes:
        print(
            f"LEFTOVER PROBE DOC: {docid} — no CLI delete exists (platform fact); "
            f"rename it manually: wecom-cli doc names update --json "
            f"'{{\"docid\":\"{docid}\",\"new_name\":\"{DELETE_ME_PREFIX}{docid}\"}}', "
            "then delete in the WeCom client and confirm in EVIDENCE"
        )
```

注意（实现者执行时）：`_create_probe` 优先取 import 响应的 `docid`（`_extract_docid` 锚点），取不到才走 search 兜底轮询——键位漂移只改锚点函数。

- [ ] **Step 2: 跑测试**

Run: `python -m pytest tests/e2e/test_wecom_undo_real.py -v -m real`
Expected: 凭据在 → 4 PASS（B5 闭环 / FM2 拒绝 / FM3 拒绝 / B8 完整性）；凭据缺 → skip（reason 注明 blocked，Task 6 EVIDENCE 如实记录）。

- [ ] **Step 3: ruff format 债清零 + Commit**

```bash
ruff format tests/e2e/test_wecom_undo_real.py
git add tests/e2e/test_wecom_undo_real.py
git commit -m "test: B5/B8 真机 e2e——wecom undo 快照写回闭环 + FM2/FM3 拒绝变体 + 内容完整性"
```

---
### Task 6: gauntlet 全绿 + agent evals（wecom 腿）+ EVIDENCE 收尾

**Files:**
- Create: `specs/2026-09-08-phase3-wecom-integration-evidence.md`（照 Phase 2 EVIDENCE 结构：凭据阻塞声明先行 → Baseline 演进 → gauntlet 各层数字 → B5/B8/B11 → 测试映射 → agent evals → 已知限制 → skip 层理由 → deferred minors → 复现入口）
- Modify: `EVIDENCE.md`（末尾追加 Phase 3 addendum 段——Status/Scope/Full report/Reproduce 四行，照 Phase 2 addendum 模式）

**Interfaces:**
- Consumes: 全部前序任务；`tools/gauntlet.sh`（diff-cover 显式门 `--fail-under 100`）；`tools/run-agent-evals.py --execute`；`tools/install-skills.sh`

- [ ] **Step 1: gauntlet fresh run（最后一次代码编辑之后）**

Run: `bash tools/gauntlet.sh`
Expected: GAUNTLET PASS——含 wecom-integration 的 conformance 参数化用例（活断言：wecom-cli 缺席即 fail）、wecom adapter fixture 测试、runner 放行测试、e2e（凭据在时实跑）；diff-cover 变更行 100%（`src/kgent/adapters/wecom.py` 是本分支唯一 src 变更文件）；mypy strict 0 错；随机序复核 `python -m pytest tests -q` 总数一致；lint 层 report-only（baseline 债务不新增——本 PR 新增文件 0 format 债已在 Task 3/5 清零）。

- [ ] **Step 2: agent evals——wecom 相关条目（release gate；执行即真实写平台）**

```bash
python tools/run-agent-evals.py --execute --file knowledge-storage-evals --ids 10
python tools/run-agent-evals.py --execute --file wiki-setup-evals --ids 3
```

探针命名纪律适用于 agent 建的文档：跑完用 `wecom-cli doc search --json '{"keywords":["escalation","wiki","home"],"search_scope":"title_content","limit":10}'` 清点租户残留，agent 建的页 rename 隔离或报告维护者处置。启发式评分只是初筛：抽读 transcript，确认 route → journal begin（含 `--snapshot-content`）→ wecom-integration 委派（file_path 内容通道）→ journal end（`--revision-after`）→ 读回 → 原生 URL（响应原样）全链在。凭据 blocked 时如实记录 skipped（EVIDENCE §0/§5），不硬跑、不以 dry-run 冒充。

- [ ] **Step 3: EVIDENCE 落盘**

`specs/2026-09-08-phase3-wecom-integration-evidence.md` 必含（母 spec「EVIDENCE 要求」节）：
- **§0 凭据阻塞声明先行**：auth 就绪与否、B5/B8 真机闭环状态（blocked 时：e2e 载体 skipif + stub 语义说明，不以 fixture 绿冒充）、B11-wecom 的 fixture 真值状态（captured vs documented-not-captured，指向 `tests/fixtures/wecom-cli/FIXTURES-NOTE.md`）、agent evals wecom 腿状态
- **§1 Baseline 演进**：起点（Phase 2 最终 579/6/0）→ 各任务交付后的数字 → 最终 fresh run
- **§2 gauntlet 各层**：命令 + 实际数字（含 skip 构成——新增的 wecom e2e 凭据门 skip 逐条带 reason）
- **§3 设计裁决的实证状态**：version 轴定谳结论（V1<V2<V3 实测读数）或 blocked 声明
- **§4 验收标准 → 测试映射**：B5（计划层 `tests/test_undo_ledger.py` wecom 机制用例 + 新鲜度读 `tests/test_wecom_adapter.py` + 真机 `tests/e2e/test_wecom_undo_real.py` 三变体）、B8（properties 共享层 + e2e）、B11-wecom（adapter fixture 测试 + conformance）；接线清单 1–4 逐条
- **§5 agent evals**：命令、评分、transcript 抽读结论、租户影响与清理
- **§6 已知限制**：bot-only、消息会话限制、速率自设退避、Fs 沙箱、无删除命令、邮件只读冲突、version 轴依赖、`?scode=` 不可构造
- **§7 skip/受限层带理由；§8 deferred minors 全清单；§9 复现入口**

`EVIDENCE.md` 末尾追加 addendum（照 Phase 2 模式四行：Status / Scope / Full report / Reproduce）。

- [ ] **Step 4: 安装与记忆**

```bash
bash tools/install-skills.sh   # 含 uv 缓存清障；wecom-integration 随 skills/*/ glob 自动装
```

项目记忆更新（`C:\Users\yong_\projects\kgent\memory\`）：Phase 3 落地状态 + wecom-cli 关键事实（`.cmd` 解析、`--json` 输入体语义、version 轴自读、Fs 沙箱 cwd 相对、无删除命令、快照写回纪律）。

- [ ] **Step 5: 最终 commit + PR（commit/push 由控制器裁决执行）**

```bash
git add specs/2026-09-08-phase3-wecom-integration-evidence.md EVIDENCE.md
git commit -m "docs: Phase 3 (wecom-integration) EVIDENCE — B5/B8/B11-wecom 验收与 gauntlet 数字"
```

PR 正文带 EVIDENCE 摘要 + agent evals 结果 + 凭据阻塞声明。

---

## Self-Review 记录

1. **spec 覆盖**：handoff §Phase 3 工作项 1（SKILL.md 契约六节 + 强制 `--snapshot-content` + 已知限制四条 + 委派矩阵）→ Task 2；项 2（DOC_FILES 追加）→ Task 2 Step 1；项 3（evals fixture wecom 腿；`git show 3da94c7` 核查无原始 wecom 写目标腿可恢复 → 新写 knowledge-storage id10 + wiki-setup id3 委派行）→ Task 4；项 4（B5 + B8；B11-wecom 随本 Phase 补，母 spec 原文「dingtalk/wecom 的类型判定用例随 Phase 补充」）→ Task 5 / Task 3；项 5（EVIDENCE 同 Phase 2 模式）→ Task 6。阻塞项（auth init 维护者本人）→ Task 1 Step 2 + Global Constraints 人工闸②。通用约定：真机探针 `-probe-` + teardown 必删（wecom 无删除 → rename 隔离等价物，平台事实）→ Task 1/5；agent evals 收尾跑 → Task 6；install-skills → Task 6 Step 4。接线清单：1（DOC_FILES）→ Task 2；2（B9 自动生效）→ Task 2 Step 3 验证；3（close 三件套）→ Task 6；4（trust_zone 显式 internal，schema 缺省 external）→ Task 1 Step 2。控制器追加项：runner allowedTools `Bash(wecom-cli:*)`（grader wecom 词 Phase 2 已覆盖不重复改）→ Task 4；progress.md Rulings 吸收——npm 安装需批准（T1 Ruling）、原生 skill 委派矩阵而非直调命令全集（T2 Ruling）、documented-not-captured（T3 前裁定）、fixture 路径 `parents[1]`/子串分发两缺陷（T3 Ruling——新测试用元素匹配分发）、skipif 让活断言不可达（T2 裁决——活断言进用例）、teardown 前缀保护 + 幂等 + BaseException（T6 fix round）、diff-cover `--fail-under 100`（T7 fix round）、新增文件 format 债为零（T7）、键位集中 `_extract_*` 锚点（T3）。
2. **占位符扫描**：全文无 TBD/「适当处理」/「类似 Task N」。⚠ 标记共三类，均为**显式对账指令**而非占位符：(a) 命令/键位形状 ⚠——Task 1 真值单（`--help`/`schema get`/真机实测）为准 + Task 2 conformance RED→GREEN 对账循环 + Task 3 `_extract_*` 锚点集中改；(b) `doc_type` 枚举/version 递增性等探针门控事实——设计裁决第 4 条给出不可满足时的**停止上报**路径（不静默绕过）；(c) SKILL.md 草稿中标 ⚠ 的行均附「按 Task 1 真值为准」。代码块均为完整可执行形态（Self-Review 轮清掉了两处草稿冗余：Task 3 长内容用例的死赋值行、adapter 未消费的 `_extract_hit_url`——避免 diff-cover 变更行 100% 门的未覆盖行假失败）。
3. **类型一致性**：`WeComAdapter(cmd: list[str] | None, timeout: float)` 与 `DingTalkAdapter` 同签名；`read_document(doc_uri: str) -> Document` 的 `metadata.version: str | None`（`_extract_version` 字符串化）与 `compensation_plan` 的 `_same_revision`（字符串化比较）及 FM3 的 `str(current.content) != before` 消费链一致（`ledger.py:145-151/294/328`）；`search_by_keywords(query, filters, top_k, fields) -> list[SearchResult]` 与 `SearchResult`/`DocumentMetadata` 字段（`rank: int`、`node_type: str`）一致；`heuristic_grade(expectations, transcript) -> tuple[int, list[str]]` 未动；journal CLI 旗标名（`--operation/--backend/--doc-uri/--revision-before/--snapshot-content` begin；`--op-id/--status/--revision-after/--doc-uri` end）与 `src/kgent/cli.py:560-590/1240` 逐一核对；e2e 的 `_kgent_json`/`--json` 叶子位与 Phase 1/2 e2e 已验证形态一致；`journal begin --revision-before` 走 CLI 的 `int()` 解析——e2e 只传数值字符串并在非数值时停（设计裁决第 4 条）。
