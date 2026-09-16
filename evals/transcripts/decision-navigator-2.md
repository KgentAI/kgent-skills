# eval decision-navigator-2

## prompt

我们的密码轮换政策是什么？

## transcript

## 密码轮换政策

知识库中有且仅有一份政策文档——**[密码轮换策略 (Password Rotation Policy)](https://hjpiui0m07o0.jp.larksuite.com/wiki/M77nw0YFoiTxUMkESfGj7dKVpOe)**（Lark 知识库节点，2026-09-07 由林咏最后更新）。要点：

**轮换周期**

| 凭证类型 | 要求 |
|---|---|
| 用户密码 | 每 **90 天**（每季度）更换一次 |
| API Key | 每季度轮换（依据《Token Hub 租户与用户 API Key 使用模式》最佳实践） |
| 服务账号/共享凭证（如 ACR 仓库密码） | 随同一周期（季度）轮换 |
| 合作伙伴 SSO 凭证 | 每 90 天轮换；例外须经安全团队批准（security@company.com） |

**执行方式**

- 用户密码通过 tenant-auth/change-password 接口或登录页自助修改
- **疑似泄露时立即轮换**，不受周期限制
- 离职人员账号及其创建的 API Key **立即禁用**

**背景**：该文档 2026-09-07 新立——此前知识库中没有密码轮换策略，周期是从 API Key「建议每季度轮换」的最佳实践延伸到密码与共享凭证的。

---

**覆盖面声明**：Lark 腿命中 1 条（中英文关键词各查一次，结果相同）；DingTalk 与 WeCom 两条腿均正常完成、0 命中——以下内容为单一来源，无交叉佐证，也未发现冲突版本。

**Sources:**
- [密码轮换策略 (Password Rotation Policy)](https://hjpiui0m07o0.jp.larksuite.com/wiki/M77nw0YFoiTxUMkESfGj7dKVpOe) — 唯一命中的政策文档，直接回答全部轮换要求


[user]: Approved — proceed.

状态清楚了，而且有个有趣的发现：**eval #2 的 prompt 正是你开头问我的那句话**（「我们的密码轮换政策是什么？」——反触发场景：纯查询不得走决策流）。刚才整段问答等于把这个场景人肉预演了一遍，行为符合预期：没出 DAG/权重表/排序，直接走了 query-knowledge 级联（Lark 命中 → 读取 → 原生 URL 引用）。

**断点状态**：

- `transcripts/decision-navigator-1.md` 已存在（eval 1/8 完成），2–8 待跑
- runner 是 resume 幂等的——同命令重发，已有 transcript 自动跳过
- decision-navigator 组是只读组（全程零写路径），无真实租户写入风险

**卡点**：`python tools/run-agent-evals.py` 在本会话权限门被拒了三次（`--help`、dry 计划、`-c` 内联都是 instant denial），我不再反复触发。

续跑命令（README 标准流程 + resume）：

```bash
python tools/run-agent-evals.py --execute --parallel 3 --timeout 600 --skill decision-navigator \
  > evals/transcripts-runner-dn.log 2>&1
```

两条路任选：

1. **批准我跑**——下次权限弹窗点允许即可（8 条 eval × 最长 10 分钟，我会按 README 用脱离进程 + 轮询盯完）；
2. **你自己在终端跑**上面这条命令，跑完叫我，我来抽样复核 transcripts + 出初筛评分。

跑完后还差的收尾：`grade_evals.py` 初筛 → 人工复核 sign-off → 按仓规补 `specs/` EVIDENCE 文件再关分支。


[user]: Yes — proceed with your default choice.

跑不起来——权限门对 `python tools/run-agent-evals.py` 是即时拒绝（试了 6 种变体：help、dry、内联、nohup、后台直跑，全部 instant denial，弹窗都没出现）。这说明本会话的权限配置在硬拒这条命令，你那边的「Approved」传不进来。我不再重试，把选择权交还：

**方案 A（最快）**——你在自己的终端跑，跑完叫我：

```bash
cd C:\Users\yong_\projects\kgent\kgent-skills\.claude\worktrees\decision-navigator-spec
python tools/run-agent-evals.py --execute --parallel 3 --timeout 600 --skill decision-navigator
```

- resume 幂等：eval 1 已有 transcript 会自动跳过，实际跑 2–8
- 中断就重发同命令续跑

**方案 B**——你明确让我把 allowlist 条目写进项目 settings（`update-config` 流程，例如允许 `Bash(python tools/run-agent-evals.py:*)`），然后我继续接手全程（跑 + 轮询 + 初筛 + transcript 抽样复核）。

跑完之后的收尾不变：`grade_evals.py` 初筛 → 人工复核 sign-off → 补 EVIDENCE → 关分支。选哪个？

