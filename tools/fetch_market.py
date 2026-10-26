#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_market.py — 拉当日大盘真实数据，用于校验播客里的点位判断

为什么必须做这件事
------------------
规则卡里的 3741 / 3674 / 3800 / 1380 / 2 万亿 / 3860 全是「他说过什么」。
没有任何一条跟当日真实行情对过。这有两个后果：

  1. 他说的点位可能是错的、记错的、或者故意说的——不校验就当成事实写进 Skill
  2. 「到点位没到」「破了没破」这类判断，只有对着真实 OHLC 才能判真假

所以每条涉及点位的规则，都要配一行「当日实际值」。

数据源（三源互备，都已实测可通）
------------------------------
  · 腾讯  web.ifzq.gtimg.cn/appstock/app/fqkline/get   日K，含成交量
  · 新浪  money.finance.sina.com.cn/.../getKLineData   日K
  · 东财  push2his.eastmoney.com/api/qt/stock/kline    日K，含成交额（易被限流）

指数代码
--------
  上证     sh000001
  深证     sz399001
  创业板   sz399006
  科创50   sh000688

用法
----
  python tools/fetch_market.py --begin 2026-09-25 --end 2026-10-22
  python tools/fetch_market.py --begin 2026-10-12 --end 2026-10-21 --out research/大盘数据.json
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

INDICES = {
    "上证": "sh000001",
    "深证": "sz399001",
    "创业板": "sz399006",
    "科创50": "sh000688",
}


def http_get(url, referer=None, timeout=25):
    hdr = dict(UA)
    if referer:
        hdr["Referer"] = referer
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


# ---------------------------------------------------------------- 数据源


def from_tencent(code, begin, end):
    """腾讯：返回 [{date, open, close, high, low, volume(手)}]"""
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={code},day,{begin},{end},320,qfq"
    )
    raw = json.loads(http_get(url, "https://gu.qq.com/"))
    node = raw.get("data", {}).get(code, {})
    rows = node.get("day") or node.get("qfqday") or []
    out = []
    for r in rows:
        # [date, open, close, high, low, volume, ...]
        out.append(
            {
                "date": r[0],
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]) if len(r) > 5 else None,
            }
        )
    return out


def from_sina(code, begin, end):
    """新浪：symbol 用 sh000001 形式"""
    n = 260
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen={n}"
    )
    raw = http_get(url, "https://finance.sina.com.cn/")
    rows = json.loads(raw) if raw.strip().startswith("[") else []
    out = []
    for r in rows:
        d = r["day"][:10]
        if not (begin <= d <= end):
            continue
        out.append(
            {
                "date": d,
                "open": float(r["open"]),
                "close": float(r["close"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "volume": float(r["volume"]) if r.get("volume") else None,
            }
        )
    return out


def from_eastmoney(code, begin, end):
    """东财：能拿到成交额（amount，元）。限流严重，放最后。"""
    mkt = "1" if code.startswith("sh") else "0"
    secid = f"{mkt}.{code[2:]}"
    b = begin.replace("-", "")
    e = end.replace("-", "")
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        "&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=0&beg={b}&end={e}"
    )
    raw = json.loads(http_get(url, "https://quote.eastmoney.com/"))
    d = raw.get("data") or {}
    out = []
    for k in d.get("klines") or []:
        p = k.split(",")
        # 日期,开,收,高,低,成交量(手),成交额(元),振幅,涨跌幅,涨跌额,换手率
        out.append(
            {
                "date": p[0],
                "open": float(p[1]),
                "close": float(p[2]),
                "high": float(p[3]),
                "low": float(p[4]),
                "volume": float(p[5]),
                "amount": float(p[6]) if len(p) > 6 else None,
            }
        )
    return out


SOURCES = [
    ("腾讯", from_tencent),
    ("新浪", from_sina),
    ("东财", from_eastmoney),
]


def fetch_one(name, code, begin, end):
    """按顺序试三个源，返回 (数据, 源名)。"""
    for sname, fn in SOURCES:
        try:
            rows = fn(code, begin, end)
            if rows:
                return rows, sname
            print(f"    {name} × {sname}: 空", file=sys.stderr)
        except Exception as ex:
            print(f"    {name} × {sname}: {type(ex).__name__}", file=sys.stderr)
        time.sleep(0.5)
    return [], None


# ---------------------------------------------------------------- 主流程


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--begin", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", default="research/大盘数据.json")
    ap.add_argument("--indices", nargs="*", default=list(INDICES))
    args = ap.parse_args()

    print(f"拉取 {args.begin} ~ {args.end}\n")
    result = {"begin": args.begin, "end": args.end, "indices": {}, "source": {}}

    for name in args.indices:
        code = INDICES[name]
        print(f"  {name} ({code})")
        rows, src = fetch_one(name, code, args.begin, args.end)
        if not rows:
            print(f"    ✗ 三源全部失败")
            continue
        result["indices"][name] = rows
        result["source"][name] = src
        print(f"    ✓ {src}  {len(rows)} 个交易日")

        # 顺带算涨跌幅和量能变化
        prev = None
        for r in rows:
            if prev and prev["close"]:
                r["pct"] = round((r["close"] - prev["close"]) / prev["close"] * 100, 2)
                if r.get("volume") and prev.get("volume"):
                    r["vol_chg_pct"] = round(
                        (r["volume"] - prev["volume"]) / prev["volume"] * 100, 1
                    )
            prev = r

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
