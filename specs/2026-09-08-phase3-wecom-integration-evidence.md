# EVIDENCE: Phase 3（wecom-integration）— skill 契约 + 台账写后快照通道 + 真机闭环

- **Spec:** `specs/2026-09-07-phase2-phase3-handoff.md` §Phase 3（母 spec
  `specs/2026-09-05-write-path-skill-delegation-design.md` v3，approved）——
  工作项 1（SKILL.md 契约）、2（DOC_FILES）、3（evals fixture wecom 腿）、
  4（B5/B8 + B11-wecom）、5（EVIDENCE + agent evals）；经 2026-09-08 计划
  修订（commit `9cd3f0d`）：version 轴真机证伪 → 维护者签核方案 A（台账
  写后快照通道），新增 Task 2、后续任务重编号
- **Tier:** 3（数据丢失域；失败模型 FM1–FM10 见母 spec）
- **Source state:** 分支 `feat/wecom-integration`，自 main @ `f77b0ed` 切出；
  §2 各行读数取于 `8dba55c`（Task 7 fresh run 时点）。**`9fec24e` 后经历兑现轮
  代码变更（`dcdec9c` dingtalk adapter 锚点 live-captured 回填、`499e94c`/
  `2af5d43` dingtalk e2e 修复）——初版「`8dba55c` 后均为 docs-only」的表述
  失真，已修正**：非 e2e 各层（全套回归 / diff-cover / mypy / artifact-smoke /
  properties / adversarial）已于 `23e2c5f` 刷新复测，刷新读数见 §2.2；e2e 真机
  证据见 §4（Task 6 wecom 5/5 × 2）与 Phase 2 EVIDENCE §0.1（兑现轮 dingtalk
  3 PASS）
- **Fresh run:** 2026-09-09，分层执行（§2）——**全量含两平台真机 e2e 的单命令
  `bash tools/gauntlet.sh` 在本环境当日不可达绿灯**，阻塞与逐层读数见 §0/§2/§7；
  随机序复核与固定序总数一致
- **Environment:** Windows 11 + Git Bash；`.venv` Python 3.12；wecom-cli
  `1.2.1 (wecom 2026-09-08T11:59:47Z e88bf90)`，auth **authorized**（2026-09-08
  扫码）；`~/.kgent/config.yaml` 的 `backends.wecom` 为
  `type: skill / skill_name: wecom-integration / trust_zone: internal`；
  dws 已登录（**Phase 2 前提变化**，见 §0）；lark-cli 用户身份有效
- **Reproduce:** 仓库根 `bash tools/gauntlet.sh`（两平台 e2e 的环境门见 §7）；
  agent evals 见 `evals/README.md`（release gate，不入 per-commit gauntlet）

## 0. 凭据与环境声明（先于一切数字）

**wecom 凭据就绪（非阻塞）**——与 Phase 2 的 dingtalk 相反，本 Phase 的真机验收
**真实跑动**，不以 fixture 绿冒充：

| 项 | 状态 |
|---|---|
| **B5 真机闭环**（undo 计划 → 快照写回 → 载荷级还原；FM2-wecom/FM3 拒绝） | **PASS × 2 次独立全绿**（2026-09-09，Task 6，`-s` 现场读数存 task-6-report §3/§4）——本 Phase 的核心真机证据，非 stub |
| **B8 真机闭环**（多段中文 + emoji + 中文标点全量保真） | **PASS**（同上；换行按真机形态钉：源 `\n` → 平台 `\r`） |
| **B11-wecom payload 真值** | **两级**：contents get / search 零命中 / import / 写操作 = **live-captured**（`tests/fixtures/wecom-cli/FIXTURES-NOTE.md` 逐键 provenance）；search **hit 形状仍 documented-not-captured**（观测窗内 search 从未返回 hit；本轮 evals/e2e 亦未捕获——search 对机器人文档不索引的形态再次复现） |
| **wecom 条目 agent evals**（knowledge-storage id10、wiki-setup id3） | **真实跑动**（§5）——非 skipped；id10 全链跑通、读回腿撞 640459 并如实上报；id3 的 wecom 腿被 harness 工具面阻断（§5.3） |
| **当日读配额（640459）** | **当日已耗尽**（Task 6 ~300 次 + 本轮）——「当日新建文档」的内容读一律 `code: 640459`，**旧文档内联读不受影响**（Task 7 真机细化，PROBE-NOTES §1.4）；重跑窗口＝配额日切（§7） |
| dws 登录态实测 | `dws auth status -f json` → `{"success": true, "authenticated": true, ...}`——**Phase 2 的「无可用钉钉账号」裁决前提已变化**：`tests/e2e/test_dingtalk_undo_real.py` 的凭据门不再 skip，无 `DWS_PROBE_CONFIRM=yes` 时确认门命令会失败并在租户留下不可经 CLI 删除的探针（`drive +delete` 同为确认门命令）——是否以 `DWS_PROBE_CONFIRM=yes` 真跑 Phase 2 遗留的 B6/B8 真机闭环，归控制器/维护者裁决（runbook：Phase 2 EVIDENCE §9） |

## 1. Baseline 演进（诚实记录）

| 时点 | 结果 | 来源 |
|---|---|---|
| Phase 2 最终 fresh run（main @ `f77b0ed`） | `579 passed, 6 skipped, 0 failed` | Phase 2 EVIDENCE |
| Task 2 交付（台账 `journal end --snapshot-after` + 写后快照新鲜度分支） | `589 passed, 7 skipped, 0 failed`（+10/+1） | task-2-report |
| Task 3 交付（wecom-integration SKILL.md + conformance 接线） | `590 passed, 7 skipped, 0 failed`（+1） | task-3-report |
| Task 4 交付（WeComAdapter 读车道，13 例） | `602 passed, 1 failed, 7 skipped`（failed 为基线内既有环境件，task-4-report Concerns） | task-4-report |
| Task 5 交付（evals wecom 腿接线 + runner 放行） | `605 passed, 7 skipped, 0 failed` | task-5-report |
| Task 6 交付（B5/B8 真机 e2e 5 测 + ledger newline 透明修复 + CR 装甲） | 排除 wecom e2e：`606 passed, 7 skipped, 0 failed`；e2e 真机 **5/5 × 2**；全量含 e2e 需配额日切（当日 640459 耗尽） | task-6-report §5/§8 |
| **Task 7 fresh run（本轮，最后一次代码编辑 `8dba55c` 之后）** | 排除两平台 e2e 文件：**`608 passed, 4 skipped, 0 failed`**（固定序 305.75s；随机序 289.43s，总数一致）＝ Task 6 的 606 + 本轮 2 条覆盖补口；两平台 e2e 的环境门见 §0/§7 | §2 |
| **兑现轮代码变更后刷新（最终评审修复轮，`23e2c5f`）** | 排除两平台 e2e 文件：**`611 passed, 4 skipped, 0 failed`**（固定序 191.92s；随机序 191.07s，总数一致）＝ Task 7 的 608 + 兑现轮 dingtalk adapter 单测 2 条（`dcdec9c`）+ 修复轮补口 1 条（`23e2c5f`）；逐层刷新读数见 §2.2 | §2.2 |

## 2. Gauntlet 各层（命令 + 实际数字）

执行方式披露：`bash tools/gauntlet.sh` 的层序在本环境当日**走不完**——pytest 层
含两平台真机 e2e（§0：wecom 腿撞 640459 当日配额、dingtalk 腿凭据前提变化后
需维护者确认门），故按 Phase 2 Task 7 同款先例**分层执行 + 排除项显式记录**，
未用 `-m` 过滤器改写测试语义、未跳过任何非 e2e 层：

| 层 | 命令（tools/gauntlet.sh 内） | 结果 |
|---|---|---|
| 工件冒烟 | `bash tools/artifact-smoke.sh` | **18/18 surface probes passed**（+1 功能探针行，见下）；探针在一次性 `KGENT_HOME` 下运行，**零真机台账写入** |
| 全套测试 | `coverage run -m pytest -p no:randomly -q --ignore=tests/e2e/test_wecom_snapshot_real.py --ignore=tests/e2e/test_dingtalk_undo_real.py` | **608 passed, 4 skipped, 0 failed**（305.75s；4 skip = 4 × POSIX mode-bit） |
| 随机序复核 | `python -m pytest tests -q`（同排除项，不关 randomly） | **608 passed, 4 skipped, 0 failed**（289.43s，与固定序总数一致） |
| 变更行覆盖 | `diff-cover coverage.xml --diff-file .diff-cover.diff --fail-under 100` | **Total 134 lines / Missing 0（100%），EXIT=0**——src 变更文件 `adapters/wecom.py`（+ `router/ledger.py`/`cli.py`）。**首轮真实读数 ≈98.5%（变更行集两处分支未覆盖；本行初版转抄的「98.1% / 133-of-233」为不可解读笔误，本轮修正为定性表述）**——diff-cover 层在本分支首次真正咬合，暴露两处无单测分支，补口 commit `8dba55c` 后复测 100%（§2.1）。兑现轮后的刷新读数见 §2.2（155/0） |
| 静态类型 | `mypy src`（strict） | **Success: no issues found in 52 source files** |
| 属性测试 | `pytest tests/properties -q` | **16 passed** |
| 对抗通过 | `pytest tests/adversarial -q` | **39 passed** |
| 真机 lark e2e | `tests/e2e/test_lark_undo_real.py`（随全套，真 lark-cli，含本轮 fresh run） | **PASS**（undo 计划 → history-revert → 读回 → teardown 0 遗留；Phase 1 起常驻的真机回归） |
| 真机 wecom e2e | `tests/e2e/test_wecom_snapshot_real.py` | **凭据就绪但当日配额阻断**：本轮两次执行 5/5 全部 `WecomDailyQuotaExhausted`（640459，fail-fast 即失败不烧轮询）；Task 6 的配额窗内读数 = **5/5 PASS × 2**（§0）；M-1 修复后 docid 到手即打印 + 失败路径自动隔离已随本轮验证 |
| 真机 dingtalk e2e | `tests/e2e/test_dingtalk_undo_real.py` | **不跑**（§0）：凭据门已开但确认门（`DWS_PROBE_CONFIRM=yes`）是维护者裁决项；无确认跑 = 必失败 + 租户遗留不可删除探针 |
| 变异 | `mutmut` / `tools/mutants.py` 兜底 | **report-only no-op**：mutmut 原生 Windows 拒跑；`tools/mutants.py` **无 Phase 3 注册项**——零 mutant 投入，如实记录 |
| Secret scan | gauntlet 内建负控 | pass |
| 网络捕获（N14） | fixture 强制 | pass |
| Lint + format | `ruff check src tests` + `ruff format --check src tests` | **report-only（显式降级裁决，Phase 1 起）**：`ruff check` 40 errors / `ruff format` 13 files（与 Phase 2 baseline 同量级）；**本分支触碰文件逐一核对 = 0 债**（`test_wecom_adapter.py`、`test_wecom_snapshot_real.py` 单文件 `ruff check`/`format --check` 双清；`tools/*` 不在 lint 层测量集） |

### 2.1 Layer A 面加严（Task 3 deferred minor → 本轮落地）与首轮 diff-cover 假阴修复

- **`journal end --snapshot-after` 功能探针行**（`tools/surface-manifest.txt`）：
  纯 `--help` 行抓不到旧 artifact——argparse 的 help 动作先于 unrecognized-args
  错误触发，缺旗标的旧 artifact 同样退 0（真机验证）。新探针行是**真实写**
  （`journal end` 对未知 op-id fail-closed 退 1），配套 `tools/artifact-smoke.sh`
  两处最小改造：探针进程整体跑在一次性 `KGENT_HOME`（mktemp + trap 清理），
  manifest 行支持 `{op_id}` 占位＝脚本预先 `journal begin` 播种的真实 op-id。
  **负控**：以「拒认 `--snapshot-after` 的 stub kgent」模拟 Phase 3 之前旧
  artifact → 该行 `FAIL` → `artifact-smoke FAILURE: 1/18 probes failed` →
  EXIT=1；现行 artifact → 18/18 → EXIT=0。
- **diff-cover 首轮 ≈98.5%（两分支未覆盖）→ 100%**（commit `8dba55c`，test-only；
  初版转抄的「98.1%」数值形式不可解读，本轮修正为定性表述）： uncovered
  两行是 `_extract_snippet` 的 string 形态容差分支（schema 契约 `string[]`，
  string 输入按未验证负载采纳）与 `_run` 的 exit-0 非对象 JSON 负控分支——
  各补一条单测（后者与 `test_dingtalk_adapter.py` 的 `[1, 2]` 负控同款）。

### 2.2 兑现轮后的刷新复测（Source state 修正，读数于 `23e2c5f`）

`9fec24e` 之后分支经历兑现轮代码变更（`dcdec9c` dingtalk adapter 锚点
live-captured 回填、`499e94c`/`2af5d43` dingtalk e2e 修复）——§2 各行读数
（`8dba55c` 时点）不再是 head 真值。非 e2e 各层已于 `23e2c5f`（最终评审修复
commit）刷新复测：

| 层 | 刷新读数（`23e2c5f`，2026-09-09） |
|---|---|
| 全套测试（固定序，同 §2 排除项） | **611 passed, 4 skipped, 0 failed**（191.92s） |
| 随机序复核 | **611 passed, 4 skipped, 0 failed**（191.07s，总数一致） |
| 变更行覆盖（对 merge-base `f77b0ed`） | **Total 155 lines / Missing 0（100%），EXIT=0**——src 变更文件 `adapters/wecom.py` + `adapters/dingtalk.py`（+ `router/ledger.py`/`cli.py`）。**刷新复跑首轮真读 99%**：兑现轮 adapter 锚点回填带入 `_extract_title` 的 `title`/`name` 两候选全缺席兜底分支无单测（`dingtalk.py:111`）→ 补口 `23e2c5f`（test-only，`8dba55c` 同款）后复测 100% |
| 静态类型 | `mypy src`（strict）：**Success: no issues found in 52 source files** |
| 工件冒烟 | `bash tools/artifact-smoke.sh`：**18/18** |
| 属性 / 对抗 | `pytest tests/properties tests/adversarial -q`：**55 passed**（16 + 39） |

真机 e2e 层不随本次刷新重跑：wecom e2e 真机读数见 §0/§2（Task 6 配额窗内
5/5 × 2）；dingtalk e2e 兑现读数见 Phase 2 EVIDENCE §0.1（3 PASS，首跑 +
独立复跑 ×2）。

## 3. 设计裁决的实证状态（修订史，全带 commit）

| 裁决 | 实证 | commit |
|---|---|---|
| **version 轴（计划原设计：undo 新鲜度走 version 递增）** | **真机证伪**：`doc contents get` 响应根本不下发 `version` 键（V1/V2/V3 三读数、text/markdown/ooxml 三档一致，`name` 同缺席）——不是不递增，是不返回 | `a41bf28`（Task 1 fix round 1，live 定谳） |
| **方案 A：扩台账写后快照通道**（被否：方案 B 内容摘要冒充 version 轴、方案 C 接受必拒） | `journal end --snapshot-after`（0600 `.after.txt`）+ `compensation_plan` 写后快照新鲜度分支（wecom：current == 写后快照才 ok） | 签核 2026-09-08 载于 progress.md；实现 `9cd3f0d`（计划修订）+ `310ab5f`（Task 2） |
| **wecom 无平台 history** → 补偿机制 = snapshot-restore、`history_hint: null` | 真机 B5 计划读数（status=ok、mechanism=snapshot-restore、history_hint=null、revision 轴恒 null） | `23d8498`（e2e 断言钉死） |
| **台账快照 IO 必须字节透明**（Task 2 实现级缺口，Task 6 真机发现） | 首轮真机 rehearsal 即 undo 恒拒现场：平台读回恒带尾部 `\r`，universal-newlines 读回把它折成 `\n` → FM2-wecom/FM3 比对恒拒；RED→GREEN 装甲（`test_compensation_plan_snapshot_round_trip_cr_transparent`，fixture 掺 `\n` 钉写侧 + 读侧双判别） | `a244a44`（修复）+ `8202577`（评审 I-1 装甲加严） |
| **快照写回不是逐字回声**（skill 文档判据修订） | 真机实测：A（`'AAA-CONTENT\r        '`）写回后读回 `'AAA-CONTENT        \r        '`——平台重排尾部 CR+padding → B5 还原判据钉**载荷级**（A 在场/B 不在场），SKILL.md Undo 节同步修订 | `23d8498`（e2e）+ `d303a82`（skill 文档对齐） |
| **640459 作用域细化**（Task 6「当日读配额、等待无效」的边界） | 真机：当日新建文档（`doc import` 与 `doc create` 两路）内容读一律 640459（长任务管线，响应带 `taskid`/`long_task_poll`）；**早前日期创建的文档内联读照常 errcode 0** → 配额探测必须用当日 docid 才有效（旧 docid 探测会假绿，本轮真机踩过）；另记 `doc create` 响应 `docid` 是 `w3_` 形（URL-token 形，非 `dc…` API docid） | PROBE-NOTES §1.4（`d303a82`） |

## 4. 验收标准 → 测试映射（B5 / B8 / B11-wecom + 接线清单）

| 行为 | 验证测试（位置） | 真值状态 |
|---|---|---|
| **B5** wecom undo 机制（快照写回闭环 + FM2-wecom/FM3 双拒绝） | 计划层：`tests/test_undo_ledger.py`（wecom 机制用例：snapshot-restore、写后快照新鲜度分支、create 腿豁免比对、CR 往返装甲）；新鲜度读：`tests/test_wecom_adapter.py::test_read_document_carries_content_without_version_axis`（version 键缺席 → `metadata.version is None`）；真机：`tests/e2e/test_wecom_snapshot_real.py` 三变体（`test_b5_undo_plan_and_snapshot_restore`：计划断言 + 快照对逐字一致 + TOCTOU 复核 + 写回后载荷级还原；`::test_b5_fm2_rejects_after_concurrent_edit`；`::test_b5_fm3_rejects_without_post_snapshot`，并钉死两通道 reason 区分） | **真机 PASS × 2**（Task 6 §3/§4/§5）——FM2/FM3 拒绝 reason 全文见 §5.4 |
| **B8** 内容完整性（多段中文 + emoji + 换行，FM7） | 共享：`tests/properties/test_content_channel.py`（16 条随全套）；真机：`tests/e2e/test_wecom_snapshot_real.py::test_b8_content_integrity`（file_path 通道 + emoji VS16 + 中文标点 + 换行真机形态断言） | **真机 PASS**（Task 6：144 bytes 读回 vs 源 136 bytes，逐 needle 断言） |
| **B11-wecom** search 类型保真（§7.2 词表 `doc`/`wiki_node`，只消费服务端事实） | `tests/test_wecom_adapter.py`（15 条：doc_type server fact 直落、词表外落 `doc` 绝不虚构 `wiki_node`、URL 段兜底判型、零命中 envelope `docs` 族缺席 → 空结果、无 docid hit 丢弃、`--limit` 封顶 100、win32 `.cmd` 解析、错误契约四条 + §2.1 补口两条）；S65 conformance 矩阵对 wecom 生效（`tests/test_adapters.py` 参数化，fake `wecom-cli` 按元素精确分发）；fixture：`tests/fixtures/wecom-cli/`（contents get / search 零命中 / search hit / import） | **两级**（§0）：contents get / 零命中 / import = live-captured；hit 形状 = schema 契约构造（documented-not-captured），键位解析集中在 `_extract_*` 锚点，补捕后只改锚点 + 回填 fixture |
| 接线 1：`DOC_FILES` 追加 | `tests/test_docs_conformance.py` `DOC_FILES` 含 `skills/wecom-integration/SKILL.md`；wecom 用例对 wecom-cli 缺席**显式 fail 不静默 skip** | 随全套 PASS（6 docs 参数化） |
| 接线 2：B9 静态检查自动生效 | `tests/test_skill_docs_integration_routing.py`（无 `kgent <op> --backends wecom` 直调、必含 `wecom-integration` 路由说明） | 随全套 PASS（2 条） |
| 接线 3：close 三件套 | 本文件 + 根 `EVIDENCE.md` addendum + `bash tools/install-skills.sh`（§5 步骤见 task-7-report） | 本轮落地 |
| 接线 4：trust_zone | `~/.kgent/config.yaml` `backends.wecom.trust_zone: internal`（Task 1，仓库外文件不入 commit） | Task 1 落地；本轮 evals 的 route 裁决实测 `internal → wecom allowed` |

## 5. agent evals（release gate——真实写平台）

命令（三组，wecom 腿**真跑不 skipped**）：

```bash
.venv/Scripts/python.exe tools/run-agent-evals.py --execute --file platform-via-integration-evals --timeout 600 --force
.venv/Scripts/python.exe tools/run-agent-evals.py --execute --file knowledge-storage-evals --ids 10 --timeout 600
.venv/Scripts/python.exe tools/run-agent-evals.py --execute --file wiki-setup-evals --ids 3 --timeout 600 --force
```

（`platform-via-integration-1` / `wiki-setup-3` 的 Phase 1/2 旧 transcript 已备份为
`*.phase1-2026-09-07.md` / `*.phase2-2026-09-08.md`。）启发式评分只是初筛；
以下抽读为人工复核结论。

### 5.1 platform-via-integration-1（lark 冒烟，真实写 lark 租户）

| 项 | 结果 |
|---|---|
| 启发式评分 | 2/6（词面评分器，prose 表述假阴，已知） |
| transcript 抽读 | **全链纪律在**：turn 1 update-first 正确 no-op（目标句已逐字在场 → 不写、不开账）→ 批准后真实更新：`route --dry-run` → `journal begin` → str_replace → `journal end ok` → **读回校验（rev 8→9）** → 原生 URL 原样引用，无 `kgent://` 泄漏；turn 2 又一次同纪律扩展（rev 9→10，provenance 指向真实租户文档） |
| 台账 | `op-20260909-1bdbb145` / `op-20260909-c57389a7` 双 op 全 `ok`（`backend=lark`、target 真实 node token） |
| 观察到的债 | begin 条目 `revision_before: null`（Phase 2 已记的同一缺口复现）——undo 对这两 op fail-closed 拒绝（§5.4 清理时实测），只能走平台 history 通道补偿 |

### 5.2 knowledge-storage-10（wecom 腿，真实写 wecom 租户）

| 项 | 结果 |
|---|---|
| 启发式评分 | 0/9（词面评分器；transcript 实际质量见下） |
| transcript 抽读 | **纪律全链在**：update-first search（零命中定谳，未假设 `docs: []`）→ proposal（provenance 三行：intent=create / target=wecom←**explicit user input** / channel=`doc create` 且论证了「短单行 ASCII 才可用 argv 内联，多行/CJK 必须走 import 两步流」）→ 批准后 `route --dry-run`（internal → wecom）→ `journal begin` → `doc create` 成功（errcode 0 + 原生 URL）→ `journal end` → **undo 补偿计划核验 ok** |
| 640459 的处理（最有价值的行为证据） | 读回腿撞当日配额 → agent **如实上报「验证不完整」**，不伪造读回、不重复硬试（两次尝试 + 一次退避即停）；并正确指出 create 腿补偿是 rename 隔离、undo 不受损 |
| 逐字判据 | transcript 主动写明还原/验证按**载荷级**（平台重排尾部空白）——skill 修订已被 agent 内化 |
| 残留与虚构点 | 建成的文档已按补偿语义 rename 隔离（§5.5）；transcript 声称 "Memory updated" **不实**（MEMORY.md mtime 未变、无该条目）；"scheduled 09:20 验证" 为 session 内虚构（headless 会话已结束，无任何调度实体） |

### 5.3 wiki-setup-3（三后端编排，真实写 lark + dingtalk 租户）

| 项 | 结果 |
|---|---|
| 启发式评分 | 1/9 |
| transcript 抽读 | **编排纪律在**：三后端 route 裁决一次给出（internal → 全允许）→ update-first 跨后端碰撞检查（lark 三页已存在且内容过期 → 判 UPDATE；dingtalk/wecom 零命中 → 判 CREATE）→ 统一 proposal（9 腿、每腿独立 op_id、repairability 提及）→ 批准后逐腿执行：**lark 3/3 更新并读回（rev 3→5）、dingtalk 3/3 创建并读回、wecom 0/3** |
| wecom 腿阻断根因（harness 级，非 skill 缺陷） | 二连：(a) **`wecom-integration` skill 未装**（repo skill，`install-skills.sh` 在 evals 之后才跑；harness 只见 `~/.claude/skills` 的 junction 与 `wecomcli-*` 原生 skills）→ agent 正确降级走原生 `wecomcli-doc`；(b) runner `--allowedTools` **无 `python`** → 原生 skill 的 `build_docx.py` 构建腿不可执行 → 3 腿停在待续状态（agent 如实报告、未伪造）。**重跑入口**：装件后（§5 步骤）`--force` 重跑本条 |
| dws 前提变化 | dingtalk 3 腿真实建成——**dws 已登录**（§0），Phase 2 的「凭据永久阻塞」不再成立 |
| 租户影响 | lark：Engineering Wiki 三页 Platform Overview 更新（内容为真实 config 状态修正，**保留并点名**，§5.5）；dingtalk：3 个新页（点名保留待维护者处置）；wecom：无写入（0/3） |

### 5.4 FM2-wecom / FM3 拒绝 reason 全文（Task 6 真机活体，EVIDENCE 归档位）

```json
FM2-wecom: {"status":"rejected","mode":"plan","integration_skill":"wecom-integration",
 "plan":{"mechanism":"snapshot-restore","snapshot_after":"<op_id>.after.txt","history_hint":null},
 "reason":"document content changed since the journaled write (post-write snapshot no longer matches); current revision None"}

FM3:       {"status":"rejected","mode":"plan",
 "plan":{"mechanism":"snapshot-restore","snapshot_after":null},
 "reason":"document content changed since the journaled write (snapshot no longer matches); current revision None"}
```

（测试额外钉死通道区分：FM3 的 reason 含 `snapshot no longer matches` 且**不含**
`post-write`——fail-closed 兜底走 begin 快照通道，非常态补票口。）
本轮清理时的补充活体：两条 lark eval op（begin 无 revision 证据）undo 均
**rejected**，reason `cannot verify freshness: no revision_after recorded and no
snapshot content available; refusing to plan a blind revert`——fail-closed 在
lark 侧同样咬人。

### 5.5 租户残留清点与处置（探针命名纪律）

| 对象 | 处置 |
|---|---|
| knowledge-storage-10 建成的 wecom 文档（Customer Escalation Hotline，`w3_ABoAF3hLAPsCNT0nneAUjRmqngi6Z_a`） | **已按 create 腿补偿语义 rename 隔离**：`kgent undo op-20260909-a308842f` 计划 ok → `doc names update` → `{"errcode":0,"errmsg":"ok"}`，现名 `kgent-phase3-probe-DELETE-ME-customer-escalation-hotline-eval10`（待维护者在 WeCom 客户端删除） |
| wiki-setup-3 的 lark 三页更新（Platform Overview × 3，rev 3→5，op `a7cc2ed6`/`5db79801`/`45c9395d`） | **保留**（内容是真实 config 状态的修正，回退等于恢复过期陈述）——点名待维护者复核 |
| wiki-setup-3 的 dingtalk 三页（alidocs 新建，op `7d5241f0`/`e29fbfdc`/`5c591c08`） | **保留并点名**（同上为真实文档；dingtalk 有删除通道，维护者可自行处置） |
| platform-via-integration-1 对 Onboarding Guide 的两次写（rev 8→9→10） | **已还原到 eval 前内容**：undo 计划因 begin 无 revision 证据 fail-closed 拒绝 → 走平台 history（`docs +history-list` 定位 rev 8 = `history_version_id 7168`）→ `docs +history-revert` → 读回核验（`Recorded 2026-09-07` 在场、`2026-09-08` 戳与扩展句均不在场）——两处 eval 改动全部消失 |
| e2e 探针（Task 7 本轮两次执行） | run 2 的 5 个 docid 全部隔离（M-1 打印捕获 + 手动 rename）；**run 1 泄漏 4 个探针 docid 未捕获**（M-1 修复前的执行），标题 `kgent-phase3-probe-临时` ×3、`kgent-phase3-probe-完整性` ×1——WeCom 客户端按 `kgent-phase3-probe` 前缀搜索人工删除（search 对机器人文档不索引，CLI 无法枚举） |
| 仓库内临时物 | `kb-init/`（wiki-setup-3 的 JSONL 草稿）、`onboarding-guide-update.md`（platform eval 残留）均已删除；transcript 备份与 runner log 不入库 |

## 6. 已知限制（spec 声明 + 实施中定谳）

1. **仅 bot 凭据、auth 一次性人工扫码**（SKILL.md Known Limitations 首条）；
   bot 是操作主体，文档归属/teardown 点名都在 bot 名下；`extra_identity_context`
   随每次响应下发，不得外泄（fixtures 已剥除）。
2. **无 version 轴、无平台 history** → undo 新鲜度与补偿完全依赖台账快照对；
   写流程漏 `--snapshot-after` 的 op 走 FM3 fail-closed（对已变更内容必拒，
   设计如此；兜底不是常态补票口）。
3. **两级限流（真机定谳）**：分钟级 850005（机器人 MCP 频率，2s 匀速节流 +
   1/2/4/15/30/60s 退避梯可穿）与当日级 640459（**只压当日新建文档的内容读**；
   等待/退避无效，只能等日切；旧文档内联读不受影响）——消费方对 640459
   fail-fast 并点名。
4. **无文档删除命令**：teardown/补偿 = rename 隔离 + 人工清理 runbook；
   CLI 无文档枚举命令且 search 不索引机器人文档 → 泄漏探针只能按标题前缀
   在客户端人工定位。
5. **Fs 沙箱**：`file_path`/`--output` 只吃 cwd 相对路径；台账快照写回前必须
   拷进 cwd；长内容读回的 `file_path` 落盘语义仍未定谳（不消费该键）。
6. **邮件只读边界（README vs docs vs help 冲突的降级定谳）**：发送通道存在
   但未验收——只读承载，确需发信走原生 skill 并明示「未经验证」。
7. **消息只达「bot 最近对话过」的会话**（sessions list 先查）。
8. **原生 URL**：`?scode=` 分享签名不可自行构造；响应无 `url` 时如实说明，
   不猜路径；URL token ≠ API docid（且 `doc create` 的 `docid` 本身就是 `w3_`
   形——两者边界比 Phase 3 初版记载更宽，PROBE-NOTES §1.4）。
9. **`doc import` 排队**：建档受理成功 ≠ 正文立即可见（分钟级转换管线），
   消费侧有界轮询（e2e 预算 24 轮 ≈3 分钟）。
10. **search 命中档键位仍 documented-not-captured**（真机从未返回 hit——机器人
    文档不被索引的形态多次复现）；解析按「键缺席即降级」，补捕只动 `_extract_*`。

## 7. 跳过/受限层（带理由）

- **全量单命令 gauntlet**：`bash tools/gauntlet.sh` 在本环境当日不可达绿灯——
  wecom e2e 5 测撞 640459 当日配额（两次执行实测全数 fail-fast，时间线：
  Task 6 尾 ~21:45 PDT 耗尽 → 23:38 PDT 仍拒；日切窗口估计 08:00 PDT
  （Beijing 日界））。**完整 PASS 需两门同开**：wecom 配额日切（届时全量
  预期 613 passed / 4 skipped / 0 failed）**且** dingtalk e2e 的 §0 裁决落地
  （确认门放行或凭据移除）——两者都齐前，完整读数以 §2 的分层执行为准。
  本轮以分层执行替代（§2），非 e2e 层零省略。
- **真机 dingtalk e2e**：凭据门已开（dws authenticated）但确认门需维护者
  `DWS_PROBE_CONFIRM=yes`（该设置即用户确认记录）；无确认跑 = 确认门命令失败
  + 探针遗留且 CLI 不可删。**裁决即得 Phase 2 遗留的 B6/B8 真机闭环。**
- **变异层**：mutmut 原生 Windows 拒跑；`tools/mutants.py` 无 Phase 3 注册项
  → 零 mutant 投入（report-only）。Phase 3 新代码以变更行 100% + S65 矩阵 +
  真机 e2e 替代。
- **lint 硬 gate**：baseline 债（40 errors / 13 files）清偿属范围外，显式
  report-only；本分支触碰文件 0 债（逐文件核对，§2）。
- **CI 跑真机 e2e**：无凭据环境用 `-m "not real"` 屏蔽；wecom e2e 另有当日
  配额窗（fail-fast，不烧 CI 时长）。

## 8. Deferred minors 全清单（progress.md 汇总，共 26 条；✅ = 已在本轮闭环）

**Task 1（真值探针 fixtures，3 条）**
1. PROBE-NOTES L9 gloss 措辞
2. §1.1 L45 PENDING-凭据 行（auth 建立后已实际补捕，行文未回改）
3. 零命中计数 5v6 转抄

**Task 2（台账写后快照通道，5 条）**
4. 报告 RED 行转抄错（scratch 文件不修，本 ledger 为准）
5. 同上 scratch 文件不修
6. ~~SKILL.md「仅写入成功后传取回全文」+「空串=合法快照」两句纪律~~ ✅ Task 3 fix round 落地（SKILL.md Write 节现行文）
7. Windows argv ~32K 上限——大文档 `--snapshot-after` 内联会撞限（stdin/临时文件通道待做；症状/后果纪律句已随最终评审修复轮回流 SKILL.md Write 节——`33dbeea`，通道本身仍 open）
8. POSIX mode 断言待 Linux CI（与 begin 侧同款 skip）

**Task 3（skill 文档，6 条）**
9. 邮件措辞张力（Write 节 vs Known Limitations 定谳句靠指针收口）
10. Undo step1 reason 措辞略宽（「写后内容已偏离证据」覆盖两通道，未逐通道点名）
11. 三处 `~/.kgent` 硬编码括注（KGENT_HOME 可迁，读字段优先）
12. create 目标文档已不存在时的幂等态靠报错兜底
13. task-3-report 131 行笔误（实 125）
14. ~~`--snapshot-after` 提为 surface-manifest 探针~~ ✅ `d303a82`（功能探针行 + artifact-smoke 配套 + 负控）

**Task 4（adapter，4 条）**
15. task-4-report Concern#1 归因误写（评审已勘误——环境件非词表对账）
16. 判型梯 L2 是 URL 在场非 type 段解析（测试 docstring 措辞高估，行为等价）
17. `ensure_ascii` 无判别断言（cmd 包装防线的间接保护）
18. FIXTURES-NOTE `doc_name` provenance 表述不准

**Task 5（evals 接线，2 条）**
19. ~~runner:185 注释漏 wecom-cli 词~~ ✅ `d303a82`
20. evals JSON 文件末尾无换行（既有状态）

**Task 6（真机 e2e，5 条 → Task 7 对齐清理，全部闭环）**
21. ~~M-1 docid 提取即打印 + 终局错误带 docid/标题/MANUAL CLEANUP~~ ✅ `d303a82`
22. ~~M-2 create 腿 end 补 `--snapshot-after`（忠实彩排 SKILL.md）~~ ✅ `d303a82`
23. ~~SKILL.md Undo 载荷级判据 + 快照 byte 透明读~~ ✅ `d303a82`
24. ~~PROBE-NOTES 回填 850005/640459/import 排队~~ ✅ `d303a82`（+ Task 7 作用域细化）
25. ~~M-3 凭据门 docstring 补 `backends.wecom.enabled` 前置~~ ✅ `d303a82`
26. ~~M-4 gauntlet 归 Task 7~~ ✅ 本轮（§2）

**Task 7 新增（本轮产出，评审点）**
- surface-manifest 功能探针行要求 artifact-smoke 配套改造（一次性 `KGENT_HOME`
  + `{op_id}` 播种）——新形态，附负控证据（§2.1）
- e2e `_create_probe` 失败路径 teardown 兜底（超出 M-1 原文的一处扩展；两次
  真机泄漏实证后补）
- wecom e2e 首轮（M-1 修复前）泄漏 4 探针 docid 未捕获（§5.5 点名）
- knowledge-storage-10 transcript 的 "Memory updated"/"scheduled 验证" 为虚构
  （真实内存未动、无调度实体）——transcript 采信纪律的又一案例
- eval harness 工具面：无 `python` allowedTool → 原生 `wecomcli-doc` 的 .docx
  构建腿不可执行；`wecom-integration` 未装时 wecom 腿降级走原生 skill

## 9. 复现入口

| 目的 | 命令 |
|---|---|
| 全部层（配额日切后即为完整 PASS 读数） | 仓库根 `bash tools/gauntlet.sh` |
| 分层读数（本轮数字来源；两平台 e2e 排除项见 §2） | `coverage run -m pytest -p no:randomly -q --ignore=tests/e2e/test_wecom_snapshot_real.py --ignore=tests/e2e/test_dingtalk_undo_real.py` → `diff-cover coverage.xml --diff-file .diff-cover.diff --fail-under 100` 等（§2 表） |
| 随机序全套（同排除项） | `.venv/Scripts/python.exe -m pytest tests -q --ignore=tests/e2e/test_wecom_snapshot_real.py --ignore=tests/e2e/test_dingtalk_undo_real.py` |
| wecom 真机 e2e（配额日切后） | `.venv/Scripts/python.exe -m pytest tests/e2e/test_wecom_snapshot_real.py -v -s -p no:randomly`（凭据门自动放行；640459 即失败并点名） |
| dingtalk 真机 e2e（Phase 2 遗留闭环，需维护者确认） | `DWS_PROBE_CONFIRM=yes .venv/Scripts/python.exe -m pytest tests/e2e/test_dingtalk_undo_real.py -v -s -p no:randomly` |
| lark 真机 e2e | `.venv/Scripts/python.exe -m pytest tests/e2e/test_lark_undo_real.py -v -s -p no:randomly` |
| agent evals（release gate） | §5 三条命令；重跑单条加 `--force`（先备份旧 transcript） |
| wecom-cli 真值 | `tests/fixtures/wecom-cli/PROBE-NOTES.md`（§1.4 含两级限流与 640459 作用域）+ `FIXTURES-NOTE.md`（逐键 provenance） |
| 安装工件 | `bash tools/install-skills.sh`（含 `uv cache clean kgent` 清障；装后 eval harness 才可见 `wecom-integration`） |
