# News Market 技能配置

# 报告生成时间
REPORT_TIME = "08:50"

# 关注的市场列表
MARKETS = [
    "上证指数",
    "深证成指",
    "创业板指",
    "恒生指数",
    "道琼斯",
    "标普500",
    "纳斯达克",
]

# 板块显示数量
SECTOR_COUNT = 5

# 飞书推送 (可选)
# FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

# A股温度计阈值
ZT_THRESHOLDS = {
    "亢奋": 100,
    "乐观": 50,
    "中性": 20,
    "谨慎": 5,
    "悲观": 0,
}
