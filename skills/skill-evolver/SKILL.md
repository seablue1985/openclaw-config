---
name: skill-evolver
description: Skill 自进化引擎。判断流程是否值得沉淀、创建/更新 Skill、去重审计、每日定时回顾。触发场景：复杂任务（≥5步工具调用）完成后自觉判断沉淀时机，以及每日 cron 回顾。
tags: [meta, self-improvement, skill, automation]
version: 1.0.0
updated_at: 2026-04-12
---

# 🧬 Skill Evolver

**"Every complex flow that repeats deserves a name."**

Skill Evolver 是主动沉淀引擎：在复杂任务（≥5 步工具调用）完成后，自动判断该流程是否值得沉淀为可复用 Skill，并在每日定时回顾中补漏遗漏的沉淀机会。

---

## 判断标准

满足以下**任一条件**即触发沉淀评估：

| 条件 | 阈值 | 说明 |
|---|---|---|
| 任务频率 | 同一类任务出现 ≥ 3 次 | 重复场景，有复用意愿 |
| 流程复杂度 | 涉及 ≥ 3 种不同工具组合 | 技术含量高 |
| 执行稳定性 | 结果可复现，不依赖临时变量 | 可标准化 |
| 节省价值 | 预计节省 ≥ 10 分钟工作量 | 实际收益明显 |

**沉默条件**（满足时不沉淀）：
- 一次性临时探索
- 涉及密钥/凭证/个人隐私数据的处理
- 依赖外部账号临时授权的流程
- 结果严重依赖随机性（AI 输出不稳定）

---

## 沉淀格式规范

### 目录结构

```
~/.openclaw/skills/<name>/
├── SKILL.md           # 必须：核心规范文件
├── scripts/           # 可选：可执行脚本
├── references/        # 可选：参考资料
└── logs/              # 自动：调用日志
```

### SKILL.md 必填字段

```markdown
---
name: <kebab-case名称>
description: <≤2句话描述，精确触发场景>
tags: [<相关标签>]
version: <语义化版本>
updated_at: <YYYY-MM-DD>
---

# <名称>

## 触发场景
<什么人/什么指令会触发这个 Skill>

## 步骤
1. <步骤1，含判断分支>
2. <步骤2>
...

## 质量检查清单
- [ ] <检查项1>
- [ ] <检查项2>

## 交付物
<Skill 执行的产出物格式>

## 注意事项
<已知的坑、局限、兼容约束>
```

---

## 去重逻辑

### 四层去重检查

**第 1 层：精确同名**
- 检查 `~/.openclaw/skills/` 是否已存在同名目录
- 若存在 → 评估是 UPDATE 还是 MERGE

**第 2 层：描述相似性（> 60% 重叠视为重复）**
- 分词对比现有 Skill 描述
- 若重叠率高 → 合并到现有 Skill，更新 `updated_at`

**第 3 层：触发词冲突**
- 若新 Skill 的触发词集合与现有 Skill 重叠 > 50%，视为冲突
- 冲突时保留更通用/被调用次数更多的版本

**第 4 层：版本号递增**
- UPDATE 时将 version 从 `x.y` 升级为 `x.y+1`（PATCH）
- 若结构发生重大变化，升级为 `(x+1).0.0`（MINOR/MAJOR）

---

## 质量检查清单

每次创建或更新 Skill 前，必须逐项确认：

- [ ] **触发条件清晰**：他人读后能独立判断何时使用
- [ ] **步骤可执行**：每步不依赖未说明的隐藏上下文
- [ ] **路径安全**：所有路径使用 `~` 或环境变量，无硬编码
- [ ] **错误处理**：有明确的失败 fallback，不是只有 happy path
- [ ] **无敏感信息**：不含密钥、token、凭证、私人数据
- [ ] **低风险验证**：已在低风险场景验证过流程可行
- [ ] **触发词唯一**：触发词不与现有 Skill 完全重叠

---

## 每日定时回顾（Cron）

### 触发时间
每天 **21:00**（非交易日也执行）

### 回顾流程

1. **扫描当天对话历史**
   - 读取 `~/.openclaw/agents/main/sessions/` 当天新增的 session JSONL
   - 提取所有 tool_call 序列，筛选 ≥ 5 步的序列

2. **候选识别**
   - 对每个 ≥ 5 步的序列，快速判断是否满足沉淀标准
   - 忽略已在 `skill_evolution_log.md` 记录的序列（去重）

3. **补漏沉淀**
   - 对识别出的遗漏机会，执行 Skill 创建或更新
   - 每条操作记录到 `skill_evolution_log.md`

4. **汇报**
   - 若当日有无沉淀机会：发飞书 DM 汇报摘要（收件人：ou_968a615509dc191f04220e18cda67080）
   - 若当日无遗漏：静默

---

## 日志格式

文件：`~/.openclaw/workspace/memory/skill_evolution_log.md`

```markdown
## 2026-04-12 21:00
- 事件：CREATE | UPDATE | MERGE | REVIEW | SKIP
- Skill名：<name>
- 触发任务：<原始任务的一句话描述>
- 满足标准：<满足哪条/哪几条判断标准>
- 产出文件：~/.openclaw/skills/<name>/SKILL.md
- 去重检查：<精确同名/描述重叠/触发词冲突/无冲突>
```

---

## 执行脚本

### skill_evolver.js

主要逻辑：

```javascript
// 1. 判断是否触发沉淀
function shouldEvolve(task) {
  if (task.toolCallCount < 5) return false;
  if (isTemporary(task)) return false;
  return meetsCriteria(task);
}

// 2. 去重检查
async function checkDuplicate(newSkill) {
  const existing = await listSkills();
  // 四层去重...
}

// 3. 创建/更新 Skill
async function evolve(task) {
  const skill = buildSkill(task);
  await checkDuplicate(skill);
  await writeSkill(skill);
  await logEvolution('CREATE', skill);
}
```

### daily_review.sh

```bash
#!/bin/bash
# 每日 21:00 定时执行
node $SKILL_DIR/scripts/skill_evolver.js --mode=review --date=$(date +%Y-%m-%d)
```

---

## 依赖

- Node.js（skill_evolver.js）
- 对话历史：`~/.openclaw/agents/main/sessions/`
- Skill 目录：`~/.openclaw/skills/`
- 日志：`~/.openclaw/workspace/memory/skill_evolution_log.md`

## 安全约束

- 禁止将密钥、凭证、token 写入 Skill 内容
- 涉及外部账号操作的 Skill，必须在 description 明确标注授权要求
- Skill 创建前必须通过质量检查清单全部项目
