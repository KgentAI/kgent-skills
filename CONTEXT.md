# kgent-skills

kgent 是联邦知识管理层：把 Lark、DingTalk、WeCom 等平台的知识内容统一为可检索、可写回、可审计的一层。kgent skills 只做编排与纪律，平台接口统一由 integration skill 承载。

## Language

**平台 (platform)**:
被接入的外部知识系统。当前：Lark/Feishu、DingTalk、WeCom。
_Avoid_: 服务、渠道

**integration skill**:
打包进 kgent-skills 的平台唯一接口层；对该平台的一切 search / read / write / undo 补偿执行 / 原生 URL 构造都必须经它，由它委派原生 skill 或平台 CLI。命名 `<platform>-integration`。
_Avoid_: 平台 skill、平台适配器

**原生 skill (native skill)**:
平台 CLI 生态自带的 agent skill（非 kgent 打包），由 integration skill 委派。
_Avoid_: 官方 skill

**后端 (backend)**:
kgent config/router 层的平台抽象，带 trust_zone。与平台一一对应：lark、dingtalk、wecom。
_Avoid_: 存储

**知识库 (knowledge base)**:
跨后端联邦全体的抽象——所有后端内容的统一视图。DingTalk 官方把 wiki space 也叫 "knowledge base"，在本项目中一律称知识空间。
_Avoid_: 文档库

**知识空间 (wiki space)**:
平台侧的知识空间容器（Lark wiki space、DingTalk workspace），平台概念而非 kgent 抽象。
_Avoid_: 空间

**kgent hosted backend**:
kgent 自有的云端托管知识库后端，与 lark / dingtalk / wecom 并列的另一种后端选择（尚未实现）；kgent CLI 平台操作（store / wiki / update / create / read / search）的唯一保留对象。三大平台的操作不经它。
_Avoid_: 本地后端、内置后端、主后端

**台账 (ledger)**:
op 级写操作账本；一个逻辑操作一条 entry，只记变更不记读。对应 CLI 命令 `journal`。
_Avoid_: 日志、审计日志（audit 是台账的读视图）

**补偿计划 (compensation plan)**:
`kgent undo` 依台账产出的待执行补偿描述（目标、机制、期望 revision）；执行归 integration skill。
_Avoid_: 回滚

**路由裁决 (routing decision)**:
kgent 对内容敏感级与目标后端的只读判定，先于任何写执行。
_Avoid_: 分流、敏感级路由

**决策导航 (decision navigator)**:
引导用户在多方案间抉择的 kgent 编排 skill（`skills/decision-navigator/`）；只编排不落盘，平台 I/O 统一经 integration skill。
_Avoid_: DecisionNavigator（仅作显示名）、决策助手

**决策意图 (decision intent)**:
用户必须在多个候选方案间做选择或承诺行动方向的请求态势；decision-navigator 的触发面，区别于纯查询（question-answering）。
_Avoid_: 提问、咨询

**决策简报 (decision brief)**:
decision-navigator 一次运行的唯一交付物：聊天内结构化答复——排序方案、对加权准则的权衡、标注假设、带原生 URL 的证据、置信度与「何者会改变排序」。v1 不落盘。
_Avoid_: 决策报告、决策文档

**决策分解 (first-principles decomposition)**:
决策简报中的显式基本面段：把决策拆解为子问题依赖图，节点标注解算状态（用户已给 / 引用来源 / 假设 / 依前未解）；开放子问题的信息需求驱动检索取材，已解节点汇成约束集、未解节点即变量集。
_Avoid_: 第一性原理（泛称）、根因分析、问题树

**评价准则 (criteria set)**:
评价方案所用的一组带权重的准则；由 decision-navigator 依澄清后的目标提出、用户确认或修改，用户显式给出的权重优先。
_Avoid_: 评分卡、rubric

**先例 (precedent)**:
检索得到的过往相关案例；只作「可能相关」呈现并必须附引用，不当作真正的类比断言。
_Avoid_: 历史案例库、案例检索

**能力盘点 (capability inventory)**:
检索开始时对当前环境可用 skill / MCP / 工具的一次性探查，用于发现 kgent 知识库之外的内部数据源。
_Avoid_: 插件发现、工具扫描
