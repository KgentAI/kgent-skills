# FIXTURES-NOTE — tests/fixtures/wecom-cli/（Phase 3 Task 1）

**Provenance: schema-shaped from `wecom-cli schema get` 机器契约 + `--help` 实测；NOT
live-captured（两个扫码窗口超时，auth 未建立，2026-09-08）。**

- 本目录两份 payload fixture 按**机器契约形状**构造，**不是真机输出**；version
  轴（V1<V2<V3 是否递增）未定谳，fixture 里 `"version": 3` 是占位整数（类型
  int32/uint32 已由 schema 钉死，**递增性没有证据**）。fixture 绿 ≠ 真机验收。
- 形状来源（按优先级）：
  1. `wecom-cli schema get doc.search / doc.contents.get / doc.import`——
     CLI 自带的机器契约（JSON Schema，含字段名/类型/enum/maxLength），**本任务
     的最强证据**（wecom-cli 与 dws 不同：`schema get` 直接给返回 payload 字段契约）；
  2. `wecom-cli <path> --help` 实测（`PROBE-NOTES.md` §1 命令真值表）；
  3. 任务书（task-1-brief）内嵌的 WebFetch 文档真值——凡与 1/2 冲突处以 schema
     为准（冲突清单见下）。
- 文件清单：
  - `doc-search.json` — `wecom-cli doc search --json '{"keywords":[...],
    "search_scope":"title_content","limit":10}'` 的期望形状。三条 hit 覆盖
    `doc_type` 三档：`doc`（有 text_highlight）、`smartpage`、`sheet`。
  - `doc-contents-get.json` — `wecom-cli doc contents get --json
    '{"docid":"..."}'` 的期望形状（`content_type` 缺省 = markdown 档，短内容
    内联返回，无 `file_path`/`document`/`errcode`/`errmsg`）。
- 值的可信度分级：**外层/容器键与叶子键名、类型**（`docs/docs_count/has_more/
  next_cursor`；hit 的 `docid/doc_name/doc_type/url/creator_userid/create_time/
  modify_time/open_time/ai_notice/title_highlight/sub_title_highlight/
  text_highlight`；get 的 `url/name/content/file_path/version`）**全部有
  schema 实证**（这比 dws 的 documented-not-captured 强一档——键位不用等补捕
  定谳，等的是**取值**）。**构造值**：docid/url/scode/creator_userid/时间串/
  高亮文本/version 数值。**解析代码不散落读这些键**：集中在
  `src/kgent/adapters/wecom.py` 模块级 `_extract_*`（键位对账锚点），补捕后
  只改锚点 + 用真实捕获件原样覆盖本目录 fixture。

## 与任务书草案构造值的冲突点（均已按 schema 实测裁决）

1. **搜索时间字段类型**：任务书草案 `create_time: 1757300000`（epoch int）；
   schema 实测 `create_time/modify_time/open_time` 是 **string，
   `YYYY-MM-DD HH:mm:ss` 格式**。fixture 取字符串（epoch 值按 UTC+8 转成同源
   时间串，相对间隔保持 0/100/200 秒）。Task 3 常量不要钉 epoch int。
2. **高亮字段类型**：任务书草案 `title_highlight: ""`（string）；
   schema 实测 `title_highlight/sub_title_highlight/text_highlight` 都是
   **string 数组**。fixture 取数组。
3. **搜索容器键**：任务书草案只有 `has_more/next_cursor/docs[]`；schema 实测
   另有 **`docs_count`**（框架自动生成的数组长度）。fixture 补上（缺省它会让
   严格比较类测试在真实输出上翻车）。
4. **hit 字段族**：schema 还有任务书未提的 `creator_name`（cpp 层注入）、
   `open_time`、`ai_notice`（智能助理来源提示语）。fixture 一并收录（`""` /
   `[]` 占位），adapter `_extract_*` 不消费的键不解析。
5. **import 的 doc_type 枚举**：schema 实测 `doc|sheet|smartsheet`，**不含
   `smartpage`**（md → 智能文档走 `smartpage.import`）；`doc.search` 的
   `doc_type` 描述则是四值。fixture 里 `smartpage` hit 保留——搜索结果会出现
   smartpage，但 import 建不出它。
6. **`version` 递增性（门控事实，未定谳）**：类型 integer 已由 schema 钉死；
   **每次编辑是否递增没有证据**（§0 两个扫码窗口超时，探针未跑）。fixture 的
   `3` 是任务书占位值；补捕 V1/V2/V3 不递增 → 立即停手上报，wecom undo 的
   新鲜度判据退到 FM3 快照内容比对，Task 3 相关常量随裁决重钉。

## 补捕回填顺序（auth 就绪后）

`PROBE-NOTES.md` §4 补捕脚本原样执行 → V1/V2/V3 读数写回 §0（裁决第 4 条
定谳）→ 真实 payload 原样覆盖本目录两份 fixture（标题敏感词换中性词，
docid/scode 保留）→ 本 NOTE 首行 provenance 改 live-captured + 回填 §3 URL
形状实测值。
