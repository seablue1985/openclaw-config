#!/usr/bin/env python3
"""
A股量化工具脚本 - 基于AkShare
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, date

try:
    import akshare as ak
except ImportError:
    print("请先安装: pip install akshare")
    sys.exit(1)


def _safe_value(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    # pandas / numpy 时间类型
    if hasattr(v, "isoformat") and "Timestamp" in type(v).__name__:
        return v.isoformat()
    # numpy scalar -> python scalar
    if hasattr(v, "item") and callable(getattr(v, "item", None)):
        try:
            return v.item()
        except Exception:
            pass
    return v


def _df_to_records(df):
    if df is None:
        return []
    df = df.copy()
    for col in df.columns:
        if "date" in str(col).lower() or "时间" in str(col):
            try:
                df[col] = df[col].astype(str)
            except Exception:
                pass
    records = df.to_dict(orient='records')
    return [{k: _safe_value(v) for k, v in row.items()} for row in records]


def get_realtime_quote_fast(symbol):
    """单票实时行情（快接口）"""
    df = ak.stock_bid_ask_em(symbol=str(symbol))
    values = {str(row["item"]): _safe_value(row["value"]) for _, row in df.iterrows()}
    return {
        "代码": str(symbol),
        "最新价": values.get("最新"),
        "涨跌幅": values.get("涨幅"),
        "涨跌额": values.get("涨跌"),
        "今开": values.get("今开"),
        "昨收": values.get("昨收"),
        "最高": values.get("最高"),
        "最低": values.get("最低"),
        "成交量": values.get("总手"),
        "成交额": values.get("金额"),
        "原始": values,
    }


def get_realtime_quotes(symbols=None):
    """实时行情"""
    if symbols:
        symbols = [str(s).strip() for s in symbols if str(s).strip()]
        if len(symbols) == 1:
            return [get_realtime_quote_fast(symbols[0])]
        # 多票批量时使用全市场快照（比 _em 更快）
        df = ak.stock_zh_a_spot()
        df["代码"] = df["代码"].astype(str)
        df = df[df["代码"].isin(symbols)]
        return _df_to_records(df)
    # 无目标时仅返回全市场快照（谨慎使用）
    df = ak.stock_zh_a_spot()
    return _df_to_records(df)


def get_historical_kline(symbol, period='daily', days=30):
    """历史K线"""
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date,
        adjust="qfq"
    )
    return _df_to_records(df)


def get_board_industry():
    """行业板块"""
    df = ak.stock_board_industry_name_em()
    return _df_to_records(df.head(20))


def get_board_concept():
    """概念板块"""
    df = ak.stock_board_concept_name_em()
    return _df_to_records(df.head(20))


def get_fund_flow(stock):
    """资金流向"""
    market = "sh" if str(stock).startswith("6") else "sz"
    df = ak.stock_individual_fund_flow(stock=stock, market=market)
    return _df_to_records(df)


def search_stock(keyword):
    """搜索股票"""
    df = ak.stock_zh_a_spot()
    # 模糊匹配代码或名称
    result = df[df['代码'].astype(str).str.contains(keyword) | df['名称'].astype(str).str.contains(keyword)]
    return _df_to_records(result.head(10))


def main():
    parser = argparse.ArgumentParser(description='A股量化工具')
    parser.add_argument('action', choices=['quote', 'kline', 'industry', 'concept', 'flow', 'search'],
                        help='操作类型')
    parser.add_argument('--symbol', help='股票代码')
    parser.add_argument('--period', default='daily', choices=['daily', 'weekly', 'monthly'])
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--keyword', help='搜索关键词')
    
    args = parser.parse_args()
    
    try:
        if args.action == 'quote':
            symbols = None
            if args.symbol:
                symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
            data = get_realtime_quotes(symbols=symbols)
            if symbols:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(data[:5], ensure_ascii=False, indent=2))
            
        elif args.action == 'kline':
            if not args.symbol:
                print("错误: 需要 --symbol 参数")
                sys.exit(1)
            data = get_historical_kline(args.symbol, args.period, args.days)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            
        elif args.action == 'industry':
            data = get_board_industry()
            print(json.dumps(data, ensure_ascii=False, indent=2))
            
        elif args.action == 'concept':
            data = get_board_concept()
            print(json.dumps(data, ensure_ascii=False, indent=2))
            
        elif args.action == 'flow':
            if not args.symbol:
                print("错误: 需要 --symbol 参数")
                sys.exit(1)
            data = get_fund_flow(args.symbol)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            
        elif args.action == 'search':
            if not args.keyword:
                print("错误: 需要 --keyword 参数")
                sys.exit(1)
            data = search_stock(args.keyword)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
