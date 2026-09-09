# FIXTURES-NOTE — tests/fixtures/wecom-cli/（Phase 3 Task 1，fix round 1 后）

**Provenance: live-captured（2026-09-08 16:56 真机捕获，auth 于第三个扫码窗口建立）。**

- 两份 payload fixture 均为**真实响应**（PROBE-NOTES §4 脚本原样跑完，SCRIPT_EXIT=0），
  仅做两处处理：`extra_identity_context` 键剥除（内含机器人/授权真人身份，CLI 明示
  禁止外泄）；其余字节原样。**fixture 绿 = 真机验收**（对本机该账号该时点而言）。
- **门控事实定谳：version 轴不成立**——`doc contents get` 三次读数（编辑已生效，
  content 串 V1≠V2≠V3）响应里**均无 `version` 键**（text/markdown/ooxml 三档一致，
  `name` 同缺席）。wecom undo 新鲜度**必走 FM3 快照内容比对**；Task 2/3/4 不得引用
  `version` 键，Task 3 常量按内容比对语义钉。
- 文件清单：
  - `doc-contents-get.json` — live-captured **V2 读数**（append 后、overwrite 前），
    键族 `errcode/content/url`。`content` 尾部 `\r` + 空格是 CLI 真实输出形态，原样保留。
  - `doc-search.json` — live-captured **零命中 envelope** `{"errcode":0,"errmsg":"ok"}`。
    探针词/kgent/probe/DELETE-ME/AAA-CONTENT/通用词「文档」六连发一致：**零命中时
    `docs/docs_count/has_more/next_cursor` 整族缺席**。这是 adapter 必须消化的真值
    （空结果 ≠ `docs: []`）。**hit 形状（`OaDocSearchDocInfo`）仍 documented-not-
    captured**：本次观测窗（~4 分钟）内 search 从未返回过 hit（导入索引延迟或机器人
    可读范围所限，未分辨）；hit 键位表以 PROBE-NOTES §2.2 的 schema 契约为准，命中档
    真实样本补捕后再落 fixture。
- 键位 provenance 分级（逐键）：
  - **live-captured**：contents get 的 `errcode/content/url`；import 响应
    `task_status/docid/url`（`task_id` 未在 succ 首响出现）；写操作响应
    `errcode/errmsg:"ok"`；search 零命中 envelope 的 `errcode/errmsg`。
  - **schema-only（纸面契约，真机未验/已证缺席）**：`OaDocSearchDocInfo` 全部 hit 键
    （`docid/doc_name/doc_type/url/creator_userid/creator_name/create_time/
    modify_time/open_time/ai_notice/title_highlight/sub_title_highlight/
    text_highlight`）；contents get 的 `name/version/file_path/document`——后两者在
    本探针（短内容、text/markdown/ooxml 档）**实测缺席**，长内容档是否落盘
    `file_path` 仍待真值。
- 解析代码不散落读这些键：集中在 `src/kgent/adapters/wecom.py` 模块级 `_extract_*`
  （键位对账锚点），并按 PROBE-NOTES §1.5「键缺席即降级」写。

## 任务书点名的四点冲突模式（对账结果，live 定谳）

1. **正常档 envelope**：定谳为**顶层字段、无 `data` 包裹**——`extra_identity_context`
   （已剥除）+ `errcode`(+`errmsg`) + 数据键直接在顶层；写操作档实测为
   `{"errcode":0,"errmsg":"ok"}`（schema 的「空对象」TypedRsp 运行时被填）。
2. **`version` 类型与递增性**：类型 int32/uint32 是纸面契约；**递增性问题作废——
   真机响应不下发 `version` 键**（PROBE-NOTES 顶部定谳）。undo 新鲜度走 FM3 内容比对。
3. **错误档键（`errcode` vs `code` 族）**：两层结构定谳——CLI 层
   `{"error":{"type","code","message"}}`（exit 1，兜底 893999，message 内嵌原始
   `[code=893xxx]`），类型化响应体内 `errcode/errmsg`（正常档带 `errcode:0`），见
   `PROBE-NOTES.md` §1.4。
4. **长内容 `file_path` 的相对/绝对语义与 Fs 沙箱边界**：本探针为短内容未触发落盘，
   **仍未定谳**（schema 只说「内容超长时框架自动落盘为文件」）——adapter 锚点在拿到
   长内容真值样本前不得消费该键，见 `PROBE-NOTES.md` §2.1/§1.5。

**构造取舍理据**：live-captured 键 → fixture 原样；schema 证明必然出现但本次未出现
的确定性字段（如命中档的 `docs_count`）→ 留在 PROBE-NOTES §2 契约表，不臆造进
fixture；出现与否未定谳的字段（`file_path`/`document`/hit 族）→ **不臆造**，等真值
样本。原 documented-not-captured 版两份构造 fixture 已被真实捕获件覆盖，不再保留
（历史形状见 git 历史 `2bf6a58`）。

## 补捕回填顺序（剩余缺口）

1. search 命中档真实样本（等索引生效或换机器人可读文档试捕）→ 覆盖
   `doc-search.json` 或新增命中档 fixture，回填 §2.2 键位表 provenance
2. `sheet`/`smartsheet`/`smartpage` 型探针的 URL `<type>` 段实测值（PROBE-NOTES §3）
3. 长内容（>阈值）contents get 的 `file_path` 落盘语义（§1.5 第 3 行）
