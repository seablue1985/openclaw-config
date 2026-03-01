#!/bin/bash
cd ~/.openclaw

# 检查是否有修改
if git diff --quiet && git diff --cached --quiet; then
    echo "$(date): No changes, skip"
    exit 0
fi

# 添加所有修改
git add -A

# 按类型分组提交
CHANGES=$(git status --porcelain)

if echo "$CHANGES" | grep -q "HEARTBEAT.md\|MEMORY.md\|memory/"; then
    git commit -m "docs: update memory and heartbeat" 2>/dev/null
elif echo "$CHANGES" | grep -q ".json\|.jsonl"; then
    git commit -m "config: update config files" 2>/dev/null
elif echo "$CHANGES" | grep -q "skills/"; then
    git commit -m "skill: update skills" 2>/dev/null
else
    git commit -m "chore: update workspace" 2>/dev/null
fi

# 推送到远端
git push origin main 2>/dev/null

echo "$(date): Backup done"
