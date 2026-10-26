#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_claims.py — 把播客里的每个点位/量能判断，拿去跟真实行情对账

为什么必须做
------------
规则卡里的 3741 / 3674 / 3800 / 1380 / 2 万亿 / 3860 全是「他说过什么」。
不跟真实行情对账，会有两个后果：

  1. 他记错了、说错了、或者 ASR 听错了，我们当成事实写进 Skill
  2. 「到点位没到」「破了没破」这类判断，只有对着真实 OHLC 才能判真假

第一版就抓到了一个大错（见下），所以这个工具是必需的，不是锦上添花。

已抓到的错
----------
**创业板 3800 vs 2800**：
  之前我靠「留下 10 个点」反推，判定 3800 成立、2800 是 ASR 错。
  **真实数据证明完全相反**：
    · 2026-09-28 ~ 10-22 创业板最高只有 3270.81，从未接近 3800
    · 10-13 创业板最低 2860.80，与 2850 差 10.8 点 → 「留下 10 个点」对上了
    · 所以「3860」是 ASR 错（应为 2860），「2800~2850」是对的
  教训：**只靠句内算术不够，必须叠加真实行情区间**。句内自洽 ≠ 事实正确。

数据口径
--------
· 点位/涨跌：腾讯日K（sh000001 / sz399001 / sz399006 / sh000688）
· 量能同比：用成交量（手）算比例。东财历史成交额接口被限流，
  改用「上证+深证成指」成交量合计的同比——口径一致，比例有效，
  但**绝对金额（2 万亿）无法逐日验证**，只能验证「放量/缩量」方向。

用法
----
  python tools/verify_claims.py
  python tools/verify_claims.py --episode 2026-10-13
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "research" / "大盘数据.json"

# 他明确说过的点位，逐条列出来对账
# kind: "level" = 当期正在被测试的支撑/压力位，必须在区间内
#       "target" = 未来目标/上限，区间外是正常的，不做区间检查
CLAIMS = [
    # (期次, 时间, 标的, 他说的值, 原话摘要, kind)
    ("2026-10-13", "00:01:25", "创业板", 2800, "创业板的底应该大概率还是在这个2800到2850之间", "level"),
    ("2026-10-13", "00:01:25", "创业板", 2850, "（同上，上沿）", "level"),
    ("2026-10-13", "00:05:57", "创业板", 2860, "创业板今天打最近打2860（ASR作3860）", "level"),
    ("2026-10-13", "00:02:07", "创业板", 2850, "这个点位上应该是创业板的2800~2850", "level"),
    ("2026-10-16", "00:10:41", "创业板", 2800, "一个是创业板的2800", "level"),
    ("2026-10-20", "00:01:02", "创业板", 2800, "第一个点是创业板的2800（ASR作3800）", "level"),
    ("2026-10-21", "00:00:28", "创业板", 2800, "创业板2800（ASR作3800）", "level"),
    ("2026-10-16", "00:10:41", "科创50", 1380, "一个是科创50的1380", "level"),
    ("2026-10-20", "00:01:08", "科创50", 1380, "第三个点是科创50的1380", "level"),
    ("2026-10-16", "00:10:41", "上证", 3741, "一个是上证的3741", "level"),
    ("2026-10-20", "00:01:08", "上证", 3741, "第二个点是上证的3741", "level"),
    ("2026-10-21", "00:00:28", "上证", 3741, "上阵的这个3741（ASR作上阵）", "level"),
    ("2026-10-16", "00:01:41", "上证", 3674, "如果说3674还跌破可能就是个位数（ASR作3074）", "level"),
    ("2026-10-19", "00:14:34", "上证", 3674, "3074就不应该被跌破", "level"),
    ("2026-10-16", "00:01:57", "上证", 4000, "反弹高度不会超过4000", "target"),
    ("2026-10-12", "00:21:28", "上证", 3741, "上证前期是3741，我说应该在3750之间", "level"),
    ("2026-10-12", "00:21:30", "创业板", 2850, "我认为底部应该在2850（ASR作3850）", "level"),
]

# 量能类判断（只能验方向，不能验绝对金额）
VOLUME_CLAIMS = [
    ("2026-10-13", "00:23:29", "两市成交额持续 2 万亿以下 → 反弹高度有限"),
    ("2026-10-13", "00:02:32", "量能同比 +5~8% 算良性，>10% 才算有资金进场"),
    ("2026-10-16", "00:10:22", "缩量的情况下价格没有太大意义"),
]


def load():
    if not DATA.exists():
        print(f"缺 {DATA}，先跑 tools/fetch_market.py", file=sys.stderr)
        sys.exit(1)
    return json.loads(DATA.read_text(encoding="utf-8"))


def nearest(rows, date):
    """取该日或之前最近的交易日"""
    cands = [r for r in rows if r["date"] <= date]
    return cands[-1] if cands else None


def verify_point(d, idx_name, level):
    """判断某点位与当日行情的关系"""
    rows = d["indices"].get(idx_name) or []
    if not rows:
        return None
    lo = min(r["low"] for r in rows)
    hi = max(r["high"] for r in rows)
    if level < lo:
        return f"区间外（全段最低 {lo:.2f}，点位在下方 {lo - level:.0f} 点）"
    if level > hi:
        return f"区间外（全段最高 {hi:.2f}，点位在上方 {level - hi:.0f} 点）"
    return "区间内 ✓"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", help="只看某一期")
    args = ap.parse_args()

    d = load()
    print(f"行情区间：{d['begin']} ~ {d['end']}")
    print(f"数据源：{d['source']}\n")

    # ---- 1. 各指数区间
    print("=" * 78)
    print("一、样本期各指数真实区间")
    print("=" * 78)
    print(f"{'指数':<8}{'最低':>10}{'最高':>10}{'末日收盘':>12}")
    print("-" * 44)
    for name, rows in d["indices"].items():
        if not rows:
            continue
        print(
            f"{name:<8}{min(r['low'] for r in rows):>10.2f}"
            f"{max(r['high'] for r in rows):>10.2f}"
            f"{rows[-1]['close']:>12.2f}"
        )

    # ---- 2. 点位对账
    print()
    print("=" * 78)
    print("二、他说的每个点位 vs 真实区间")
    print("=" * 78)
    print(f"{'期次':<12}{'标的':<8}{'点位':>8}  判定")
    print("-" * 78)
    bad = []
    for ep, tm, idx, level, quote, kind in CLAIMS:
        if args.episode and ep != args.episode:
            continue
        if kind == "target":
            verdict = "目标/上限类，不做区间检查（区间外属正常）"
            print(f"{ep:<12}{idx:<8}{level:>8}  · {verdict}")
            continue
        verdict = verify_point(d, idx, level)
        flag = "✓" if verdict and "区间内" in verdict else "⚠"
        if flag == "⚠":
            bad.append((ep, tm, idx, level, quote, verdict))
        print(f"{ep:<12}{idx:<8}{level:>8}  {flag} {verdict}")

    # ---- 3. 逐日点位穿越
    print()
    print("=" * 78)
    print("三、关键点位逐日穿越情况（上证 3741 / 3674）")
    print("=" * 78)
    sh = d["indices"].get("上证") or []
    print(f"{'日期':<12}{'最低':>9}{'收盘':>9}   3741      3674")
    print("-" * 60)
    for r in sh:
        a = "破" if r["low"] < 3741 else ("触" if r["low"] < 3760 else "—")
        b = "破" if r["low"] < 3674 else ("触" if r["low"] < 3690 else "—")
        print(f"{r['date']:<12}{r['low']:>9.2f}{r['close']:>9.2f}    {a:<8}  {b}")

    # ---- 4. 量能方向
    print()
    print("=" * 78)
    print("四、量能方向（上证+深证成指 成交量合计同比）")
    print("=" * 78)
    sh_rows = {r["date"]: r for r in (d["indices"].get("上证") or [])}
    sz_rows = {r["date"]: r for r in (d["indices"].get("深证") or [])}
    common = sorted(set(sh_rows) & set(sz_rows))
    print(f"{'日期':<12}{'量(手)':>16}{'同比%':>9}  判读")
    print("-" * 62)
    prev = None
    for dt in common:
        v = sh_rows[dt]["volume"] + sz_rows[dt]["volume"]
        chg = None
        note = ""
        if prev:
            chg = (v - prev) / prev * 100
            if chg > 10:
                note = ">10% 他说「有资金进场」"
            elif 5 <= chg <= 8:
                note = "+5~8% 他说「良性」"
            elif chg < 0:
                note = "缩量 → 他说「价格没意义」"
        print(
            f"{dt:<12}{v:>16,.0f}"
            f"{(f'{chg:+.1f}' if chg is not None else '—'):>9}  {note}"
        )
        prev = v
    print()
    print("⚠️ 口径说明：东财历史成交额接口被限流，这里用成交量（手）合计算同比。")
    print("   比例方向有效，但「2 万亿」这类绝对金额无法逐日验证。")

    # ---- 5. 问题清单
    if bad:
        print()
        print("=" * 78)
        print("五、需要修正的点位")
        print("=" * 78)
        for ep, tm, idx, level, quote, verdict in bad:
            print(f"  ⚠️ {ep} {tm}  {idx} {level}")
            print(f"     原话：{quote}")
            print(f"     判定：{verdict}")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
