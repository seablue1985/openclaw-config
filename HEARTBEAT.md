# HEARTBEAT.md

## 每次心跳检查

1. 读取 `memory/` 目录，检查最近日志
2. 如果有待办任务，优先处理
3. 没有需要注意的事 → 回复 HEARTBEAT_OK

## 定期维护（每几小时）

1. 检查最近的 `memory/YYYY-MM-DD.md`
2. 提取重要信息更新 `MEMORY.md`
3. 清理过期内容
