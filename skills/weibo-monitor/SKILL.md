# Weibo Monitor Skill（微博监控 V2）

监控指定微博博主的最新发文，**自动分析内容 + 评论情绪汇总**，有高价值内容时推送飞书通知。

## 功能

| 功能 | 说明 |
|------|------|
| 📡 新微博监测 | 定时检测博主最新发布 |
| 📝 内容分析 | 自动识别股票/金融市场相关内容 |
| 💬 评论抓取 | 获取每条微博的评论区（最多5页） |
| 😊 情绪分析 | 基于关键词统计正面/负面情绪倾向 |
| 🏆 高赞评论 | 展示评论获赞排名 |
| 📲 飞书推送 | 有股票相关内容时自动推送完整报告 |

## 监控对象

- UID: `2014433131`（已配置）

## 配置

### Cookie（已配置）
`config/cookie.env` — 已保存微博登录态，无需修改。

### 博主任意添加
编辑 `scripts/fetch_weibo_v2.py` 里的 `WATCHLIST` 列表：
```python
WATCHLIST = [
    {"uid": "2014433131", "name": "博主昵称"},
    {"uid": "其他UID", "name": "其他昵称"},
]
```

### 股票关键词
编辑 `STOCK_KEYWORDS` 列表可自定义筛选关键词。

## 使用方法

### 手动运行
```bash
/usr/bin/python3 /Users/ling/.openclaw/skills/weibo-monitor/scripts/fetch_weibo_v2.py
```

### 自动运行
LaunchAgent 已配置，每 30 分钟自动检测一次。

```bash
# 查看日志
cat /Users/ling/.openclaw/skills/weibo-monitor/logs/weibo_monitor.log

# 重启服务
launchctl unload ~/Library/LaunchAgents/com.ling.weibo-monitor.plist
launchctl load ~/Library/LaunchAgents/com.ling.weibo-monitor.plist
```

## 推送示例

收到推送时，内容包含：
- 📝 博主原文摘要
- 💬 评论数量 + 情绪倾向（正面词/负面词统计）
- 👥 高赞评论 Top3
- 🔗 原文链接

## 状态管理

状态文件保存在 `state/last_post_id.json`，自动跳过已推送的微博，无需手动管理。
