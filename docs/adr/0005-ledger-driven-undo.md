# 0005 — undo 是台账驱动的补偿，不是直接回滚

写操作前 `journal begin`（op_id 含 uuid 后缀——历史实现按日期发号，同日全部操作撞号 `op-YYYYMMDD-NN`，按 id 回滚必然错乱，且实测 undo 返回 ok 却不恢复内容），写后 `journal end`。`kgent undo` 依台账产出补偿计划：Lark → `docs +history-revert`、DingTalk → `dws +version-revert`、WeCom 无平台 history → 台账内容快照写回。计划由 integration skill 执行；执行前做新鲜度检查——当前 revision 与台账"写后 revision"不符即拒绝，防止埋掉他人并发编辑。

## Consequences

- 补偿是最终一致的恢复手段，不保证原子；新鲜度检查使 undo 在并发编辑后 fail closed 而非静默覆盖。
- journal 目录含内容明文快照（WeCom 补偿依赖它）：已知限制，文件权限收紧、目录不入库。
