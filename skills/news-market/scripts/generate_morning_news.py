#!/usr/bin/env python3
"""
全球股市早间要闻生成器
用法: python3 generate_morning_news.py [--output OUTPUT_PATH]
"""

import argparse
import datetime
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import akshare as ak
    import yfinance as yf
except ImportError:
    print("请先安装依赖: pip install akshare yfinance")
    sys.exit(1)


def get_A股大盘数据():
    """获取A股大盘情绪数据"""
    try:
        # 涨跌停数据
        df = ak.stock_zt_pool_em(date=datetime.datetime.now().strftime("%Y%m%d"))
        zt_count = len(df) if df is not None else 0
        
        # 成交量
        df_vol = ak.index_zh_a_hist(symbol="000001", period="daily", start_date=datetime.datetime.now().strftime("%Y%m%d"), end_date=datetime.datetime.now().strftime("%Y%m%d"))
        vol = df_vol['成交量'].iloc[-1] if len(df_vol) > 0 else 0
        
        # 简单情绪评分 (基于涨跌停)
        if zt_count >= 100:
            score = "亢奋"
            opinion = "看涨"
        elif zt_count >= 50:
            score = "乐观"
            opinion = "看涨"
        elif zt_count >= 20:
            score = "中性"
            opinion = "中性"
        elif zt_count >= 5:
            score = "谨慎"
            opinion = "看跌"
        else:
            score = "悲观"
            opinion = "看跌"
        
        return {
            "涨停数": zt_count,
            "成交量": vol,
            "情绪评分": score,
            "判断": opinion
        }
    except Exception as e:
        return {"涨停数": 0, "成交量": 0, "情绪评分": "未知", "判断": "中性", "error": str(e)}


def get_板块数据():
    """获取板块涨跌数据"""
    try:
        df = ak.stock_board_industry_name_em()
        df = df.sort_values('涨跌幅', ascending=False)
        
        top5 = df.head(5)[['名称', '涨跌幅', '成交额']].to_dict('records')
        bottom5 = df.tail(5)[['名称', '涨跌幅', '成交额']].to_dict('records')
        
        return {"涨幅前5": top5, "跌幅前5": bottom5}
    except Exception as e:
        return {"涨幅前5": [], "跌幅前5": [], "error": str(e)}


def get_全球市场数据():
    """获取全球主要市场数据"""
    markets = {
        "上证指数": "000001.SS",
        "深证成指": "399001.SZ",
        "创业板指": "399006.SZ",
        "恒生指数": "^HSI",  # 改为HSI指数
        "道琼斯": "^DJI",
        "标普500": "^GSPC",
        "纳斯达克": "^IXIC",
    }
    
    result = {}
    for name, ticker in markets.items():
        try:
            if ticker.endswith(".HK"):
                data = yf.Ticker(ticker).history(period="1d")
            else:
                data = yf.Ticker(ticker).history(period="1d")
            
            if len(data) > 0:
                price = data['Close'].iloc[-1]
                prev = data['Open'].iloc[-1]
                change = (price - prev) / prev * 100
                result[name] = {"价格": round(price, 2), "涨跌幅": round(change, 2)}
        except Exception as e:
            result[name] = {"价格": "-", "涨跌幅": "-", "error": str(e)}
    
    return result


def get_新闻摘要():
    """获取今日股市新闻摘要"""
    # 简化版本：返回placeholder
    # 实际可以接入东方财富、同花顺等新闻API
    return [
        "A股三大指数昨日震荡上行，市场情绪有所回暖",
        "港股科技股集体反弹，腾讯、阿里巴巴领涨",
        "美股三大指数小幅收涨，纳指再创新高",
    ]


def generate_report():
    """生成早间报告"""
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    report = f"""# 📰 全球股市早间要闻
**生成时间**: {today}

---

## 📈 全球市场概览

| 市场 | 涨跌幅 |
|------|--------|
"""
    
    # 全球市场数据
    global_data = get_全球市场数据()
    for name, data in global_data.items():
        change = data.get('涨跌幅', '-')
        emoji = "🟢" if isinstance(change, (int, float)) and change > 0 else "🔴" if isinstance(change, (int, float)) and change < 0 else "⚪"
        report += f"| {name} | {emoji} {change}% |\n"
    
    report += """
---

## 🌡️ A股大盘体温
"""
    
    # A股数据
    a股_data = get_A股大盘数据()
    report += f"""
- **涨停数**: {a股_data.get('涨停数', '-')}
- **成交量**: {a股_data.get('成交量', '-')}
- **情绪评分**: {a股_data.get('情绪评分', '未知')}
- **判断**: {a股_data.get('判断', '中性')}
"""

    report += """
---

## 🔥 板块热力图

### 涨幅前5
"""
    
    sector_data = get_板块数据()
    for i, item in enumerate(sector_data.get('涨幅前5', [])[:5], 1):
        report += f"{i}. {item.get('名称', '-')} {item.get('涨跌幅', 0):+.2f}%\n"
    
    report += "\n### 跌幅前5\n"
    for i, item in enumerate(sector_data.get('跌幅前5', [])[:5], 1):
        report += f"{i}. {item.get('名称', '-')} {item.get('涨跌幅', 0):+.2f}%\n"
    
    report += """
---

## 🎯 判断与建议

"""
    
    # 综合判断
    a股_judge = a股_data.get('判断', '中性')
    if a股_judge == "看涨":
        recommendation = "✅ 建议适度参与，关注热门板块"
    elif a股_judge == "看跌":
        recommendation = "⚠️ 建议控制仓位，谨慎操作"
    else:
        recommendation = "➡️ 建议保持中性观望"
    
    report += f"""- **大盘判断**: {a股_judge}
- **操作建议**: {recommendation}

---

*本报告由AI自动生成，仅供参考*
"""
    
    return report


def main():
    parser = argparse.ArgumentParser(description="全球股市早间要闻生成器")
    parser.add_argument("--output", "-o", help="输出文件路径", default=None)
    args = parser.parse_args()
    
    print("📰 正在生成全球股市早间要闻...")
    
    try:
        report = generate_report()
        
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
            print(f"✅ 报告已保存至: {args.output}")
        else:
            print(report)
        
        return 0
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
