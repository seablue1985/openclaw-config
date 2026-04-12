#!/usr/bin/env node
/**
 * Skill Evolver — 自进化引擎
 * 
 * 用法：
 *   node skill_evolver.js --mode=create --task=<描述>
 *   node skill_evolver.js --mode=review --date=2026-04-12
 *   node skill_evolver.js --mode=check --session=<sessionKey>
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = os.homedir();
const SKILL_DIR = path.join(HOME, '.openclaw', 'skills');
const WORKSPACE = path.join(HOME, '.openclaw', 'workspace');
const LOG_FILE = path.join(WORKSPACE, 'memory', 'skill_evolution_log.md');
const SESSION_DIR = path.join(HOME, '.openclaw', 'agents', 'main', 'sessions');

// ─── 工具函数 ────────────────────────────────────────────────

function log(msg) {
  console.log(`[skill-evolver] ${msg}`);
}

function error(msg) {
  console.error(`[skill-evolver ERROR] ${msg}`);
}

function readJsonl(filePath) {
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    return content.trim().split('\n').filter(Boolean).map(line => {
      try { return JSON.parse(line); } catch { return null; }
    }).filter(Boolean);
  } catch {
    return [];
  }
}

function fileExists(p) {
  try { fs.statSync(p); return true; } catch { return false; }
}

function mkdirp(p) {
  try { fs.mkdirSync(p, { recursive: true }); } catch {}
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

// ─── 沉淀判断 ─────────────────────────────────────────────────

/**
 * 判断一个任务是否值得沉淀
 * @param {object} task - { description, toolCallCount, toolTypes, isTemporary, recurring }
 */
function shouldEvolve(task) {
  if (task.toolCallCount < 5) {
    log(`工具调用${task.toolCallCount}次，低于阈值5，跳过`);
    return false;
  }
  if (task.isTemporary) {
    log('标记为临时任务，跳过');
    return false;
  }
  const criteria = [];
  if (task.recurring >= 3) criteria.push('frequency');
  if (new Set(task.toolTypes).size >= 3) criteria.push('complexity');
  if (criteria.length === 0) {
    log('不满足任何沉淀标准，跳过');
    return false;
  }
  log(`满足沉淀标准: ${criteria.join(', ')}`);
  return { criteria, reason: criteria.join(' + ') };
}

// ─── 去重检查 ─────────────────────────────────────────────────

async function checkDuplicate(skillName) {
  const skillPath = path.join(SKILL_DIR, skillName);
  if (fileExists(skillPath)) {
    return { duplicate: true, action: 'UPDATE', path: skillPath };
  }

  // 检查描述相似性
  try {
    const dirs = fs.readdirSync(SKILL_DIR);
    for (const dir of dirs) {
      if (!fileExists(path.join(SKILL_DIR, dir, 'SKILL.md'))) continue;
      const content = fs.readFileSync(path.join(SKILL_DIR, dir, 'SKILL.md'), 'utf8');
      const similarity = textSimilarity(skillName, content);
      if (similarity > 0.6) {
        return { duplicate: true, action: 'MERGE', path: path.join(SKILL_DIR, dir), similarTo: dir };
      }
    }
  } catch {}

  return { duplicate: false, action: 'CREATE' };
}

function textSimilarity(a, b) {
  const tokensA = new Set(a.toLowerCase().split(/[\s\-_]/));
  const tokensB = new Set(b.toLowerCase().split(/[\s\-_]/));
  const intersection = [...tokensA].filter(t => tokensB.has(t)).length;
  const union = new Set([...tokensA, ...tokensB]).size;
  return union > 0 ? intersection / union : 0;
}

// ─── 创建 Skill ────────────────────────────────────────────────

async function createSkill(name, task) {
  const skillPath = path.join(SKILL_DIR, name);
  mkdirp(path.join(skillPath, 'scripts'));
  mkdirp(path.join(skillPath, 'logs'));
  mkdirp(path.join(skillPath, 'references'));

  const now = new Date().toISOString().slice(0, 10);
  const skillMd = `---
name: ${name}
description: ${task.description || '（待补充）'}
tags: [auto-generated]
version: 1.0.0
updated_at: ${now}
---

# ${name}

## 触发场景
${task.trigger || '（待补充）'}

## 步骤
${task.steps || '（待补充）'}

## 质量检查清单
- [ ] 触发条件描述清晰
- [ ] 步骤可逐条执行
- [ ] 无硬编码路径
- [ ] 有错误处理
- [ ] 不含敏感信息
- [ ] 经低风险场景验证

## 交付物
${task.output || '（待补充）'}

## 注意事项
${task.notes || '（暂无）'}
`;

  fs.writeFileSync(path.join(skillPath, 'SKILL.md'), skillMd, 'utf8');
  log(`Skill 创建完成: ${skillPath}`);
  return skillPath;
}

// ─── 记录日志 ─────────────────────────────────────────────────

function logEvolution(event, skillName, details) {
  const now = new Date().toISOString().replace('T', ' ').slice(0, 16);
  const entry = `## ${now}\n- 事件：${event}\n- Skill名：${skillName}\n- 触发任务：${details.task || ''}\n- 满足标准：${details.criteria || ''}\n- 产出文件：${details.path || ''}\n- 去重检查：${details.dedup || ''}\n`;
  
  if (fileExists(LOG_FILE)) {
    const existing = fs.readFileSync(LOG_FILE, 'utf8');
    fs.writeFileSync(LOG_FILE, existing + '\n' + entry);
  } else {
    mkdirp(path.dirname(LOG_FILE));
    fs.writeFileSync(LOG_FILE, `# Skill Evolution Log\n\n${entry}`);
  }
  log(`日志已写入: ${LOG_FILE}`);
}

// ─── 每日回顾模式 ─────────────────────────────────────────────

async function dailyReview(dateStr) {
  log(`开始每日回顾: ${dateStr}`);
  const { sessions, sessionsIndex } = findTodaySessions(dateStr);
  
  if (sessions.length === 0) {
    log('当日无会话记录');
    return { reviewed: 0, candidates: [], actions: [] };
  }

  const candidates = [];
  for (const session of sessions) {
    const toolCalls = extractToolCalls(session);
    if (toolCalls >= 5) {
      const result = shouldEvolve({
        toolCallCount: toolCalls,
        toolTypes: session.toolTypes || [],
        recurring: 1,
        isTemporary: false,
        description: session.description || '会话片段'
      });
      if (result) {
        candidates.push({ session, result, toolCalls });
      }
    }
  }

  log(`发现 ${candidates.length} 个候选沉淀机会`);
  return { reviewed: sessions.length, candidates };
}

function findTodaySessions(dateStr) {
  try {
    const indexFile = path.join(SESSION_DIR, 'sessions.json');
    if (!fileExists(indexFile)) return { sessions: [], sessionsIndex: {} };
    const index = JSON.parse(fs.readFileSync(indexFile, 'utf8'));
    const todaySessions = Object.values(index)
      .filter(s => s.lastMessageAt && s.lastMessageAt.startsWith(dateStr))
      .map(s => ({ ...s, filePath: path.join(SESSION_DIR, s.id + '.jsonl') }))
      .filter(s => fileExists(s.filePath));
    return { sessions: todaySessions, sessionsIndex: index };
  } catch {
    return { sessions: [], sessionsIndex: {} };
  }
}

function extractToolCalls(session) {
  try {
    const content = fs.readFileSync(session.filePath, 'utf8');
    const lines = content.trim().split('\n');
    return lines.filter(l => {
      try {
        const obj = JSON.parse(l);
        return obj.type === 'assistant' && obj.tool_calls && obj.tool_calls.length > 0;
      } catch { return false; }
    }).length;
  } catch {
    return 0;
  }
}

// ─── CLI 入口 ─────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const mode = args.find(a => a.startsWith('--mode='))?.split('=')[1] || 'check';
  const taskArg = args.find(a => a.startsWith('--task='))?.split('=')[1] || '';
  const dateArg = args.find(a => a.startsWith('--date='))?.split('=')[1] || today();

  if (mode === 'create') {
    const task = { description: taskArg, toolCallCount: 999, toolTypes: ['file', 'exec', 'read', 'write', 'edit'], isTemporary: false, recurring: 3 };
    const result = shouldEvolve(task);
    if (!result) { log('不满足沉淀条件，退出'); return; }
    
    const skillName = args.find(a => a.startsWith('--name='))?.split('=')[1];
    if (!skillName) { error('--name=<skill-name> 必须指定'); return; }
    
    const dup = await checkDuplicate(skillName);
    log(`去重结果: ${dup.action}`);
    
    const skillPath = await createSkill(skillName, { description: taskArg, steps: '（见 SKILL.md）' });
    logEvolution(dup.action, skillName, { task: taskArg, criteria: result.reason, path: skillPath, dedup: dup.action });
  }
  else if (mode === 'review') {
    const result = await dailyReview(dateArg);
    log(`回顾完成: ${result.reviewed} 个会话, ${result.candidates.length} 个候选`);
    if (result.candidates.length > 0) {
      console.log('候选列表:');
      result.candidates.forEach((c, i) => {
        console.log(`  ${i + 1}. [${c.toolCalls}步] ${c.session.description || c.session.id}`);
      });
    }
  }
  else if (mode === 'check') {
    const skillName = args.find(a => a.startsWith('--name='))?.split('=')[1];
    if (!skillName) { error('--name=<skill-name> 必须指定'); return; }
    const dup = await checkDuplicate(skillName);
    console.log(JSON.stringify(dup, null, 2));
  }
}

main().catch(err => { error(err.message); process.exit(1); });
