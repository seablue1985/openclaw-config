# OpenClaw News Monitor Skill

监控 OpenClaw 生态的最新动态，有更新时推送到飞书。

## 功能

| 功能 | 说明 |
|------|------|
| 🔄 版本检测 | 自动检测 OpenClaw 是否有新版本发布 |
| 🔥 GitHub 热门 | AI Agent 相关热门开源项目（每日监控） |
| 📝 更新日志 | OpenClaw 最新 commits |
| 📲 飞书推送 | 有更新时自动推送报告 |

## 监控范围

- **OpenClaw 版本更新** — 与 github.com/openclaw/openclaw/releases 对比
- **GitHub AI Agent 热门** — 搜索 AI agent / autonomous agent 相关热门项目
- **OpenClaw commits** — 最新代码更新

## 推送规则

- OpenClaw 有新版本 → 立即推送
- GitHub 出现爆款热门项目 → 推送
- 每天 08:00 定期检查（无更新则不推送）

## 使用方法

```bash
# 手动检查
/usr/bin/python3 /Users/ling/.openclaw/skills/openclaw-news-monitor/scripts/check_openclaw_news.py
```

## 状态管理

状态保存在 `state/openclaw_news_state.json`，自动去重不会重复推送。
