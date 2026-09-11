# 0006 — query-knowledge 取代 question-answering

question-answering skill 更名并扩界为 query-knowledge。触发单位从"用户提问"改为"任务的知识依赖"（见 CONTEXT.md）：直接提问仍然触发；任何需要知识库事实的任务——起草 PRD、设计营销活动、处理客诉、制作季报、提炼业务洞察——同样触发。输出保持单一形态：grounded 答案 + 原生 URL 引用；发现冲突（S55）或知识库缺口（N11）时，无论哪种触发都必须指出。Python 层同步干净改名：`question_answering.answer` → `query_knowledge.query_knowledge`，无兼容别名。

## Considered Options

- **`kgent:` 冒号命名空间**：被否——冒号不能做目录名（NTFS 保留字），agent skill 名约定 `[a-z0-9-]`；用户裁决用裸名 `query-knowledge`。
- **双形态输出（answer + knowledge brief 两套骨架）**：被否——任务语境下的答案就是下游任务的知识输入，冲突与缺口照常指出即可，不值得第二套输出模板。
- **兼容别名（`answer` 保留一个发布周期）**：被否——私有仓、无外部调用方，双名徒增文档漂移面。

## Consequences

- eval fixture 随改名：`question-answering-evals.json` → `query-knowledge-evals.json`（文件名即 eval id 前缀）；新增任务语境触发用例。旧 transcripts 是历史记录，不改名不删除。
- 安装器按 `skills/*/` 发现，改名后旧链接（`~/.agents/skills/question-answering`）成为悬挂项且不被 update/uninstall 触及（两者都遍历 repo 现存目录）——安装器须回收"目标指向本仓 skills/ 且已不存在"的自有悬挂项；共享 hub 里非本仓条目一律不动。
- ADR 0004 正文里出现的旧名是历史记录，不改；本 ADR 取代其对 skill 名称的提法。
- 触发扩界的纪律靠 SKILL.md 的 description + 知识依赖判据；若实测过触发（无关任务频繁空搜），fallback 是把判据收紧为显式任务类型列表，并在本 ADR 追记。
