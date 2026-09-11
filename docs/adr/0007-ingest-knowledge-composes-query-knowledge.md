# 0007 — ingest-knowledge 取代 knowledge-storage；写前语境经 query-knowledge

knowledge-storage skill 更名并扩界为 ingest-knowledge（与 0006 的 query-knowledge 同模式的裸名改名；Python 层同步 `knowledge_storage.store_workflow` → `ingest_knowledge.ingest_knowledge`，无别名）。行为裁决一条：**ingest-knowledge 的 update-first 内容发现不再自带检索步骤，改为调用 query-knowledge 收集语境**——找既有匹配、读匹配内容出预览、识别 non-docx 目标，都走读车道；query-knowledge 返回的匹配候选（URI、node_type、标题、新近度、内容类型）作为 ingest 提案的输入。update-first 偏置本身（N18/S61，先搜后建）不变，变的只是谁来搜。

## Considered Options

- **保留 ingest 自带检索（只改名）**：被否——读车道会有两套检索纪律（query-knowledge 的知识与 ingest 的简化版），漂移只是时间问题。
- **wiki-setup 的碰撞检索同样改走 query-knowledge**：本 ADR 不做——它的检索是单页标题级碰撞检查，作用域窄且与建页提案紧耦合；观察到漂移再收编，届时追记本 ADR。
- **Python 层 `ingest_knowledge()` 内部改调 `query_knowledge()`**：被否——Python 原语是 router 级编排（S65），不跨 skill 调用；组合发生在 agent 流程层（SKILL.md），由 agent eval 断言。

## Consequences

- 分层仍守 ADR 0004：ingest → query-knowledge → `<platform>-integration` → 原生 CLI/skill，没有绕过 integration skill 的新通路。
- query-knowledge 的单一输出形态不变（0006）；被别的 skill 调用时同一流程照走，调用方消费匹配候选，不要求面向用户的答案稿。
- 写后读回（read-back）留在 ingest：它是写序列的验证段，不是内容发现；仍经 integration skill。
- eval fixture 改名 `knowledge-storage-evals.json` → `ingest-knowledge-evals.json`；新增"update-first 发现走 query-knowledge 流"期望用例；旧 transcripts 为历史记录不动。写域分组（ingest 有台账写入）在 evals/README 分区中的地位不变。
