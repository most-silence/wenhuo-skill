#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_transcript.py — 转写稿质量体检 + 后处理

为什么需要
----------
faster-whisper 转中文股市播客有四种固定毛病，肉眼看不出来但会污染蒸馏：

  1. **繁体字混入**：medium 会在句中突然输出「結果」「這」「資金」。
     实测 8 集小模型稿命中 466 个繁体字。不处理会让术语匹配全部失效。
     → 用 OpenCC t2s 转换（已验证：「結果在11點25」→「结果在11点25」）
  2. **同音词替换**：量能→亮能、盘面→旁边、危险区→卫生区、筑底→注底、
     很妖→很腰、一股劲→一股近。这类只影响术语准确性，不影响到通顺。
  3. **数字读错**：点位（3741）、百分比（8%）。
  4. **语气词堆积**：啊/呃/呢/对吧，蒸馏时要过滤但不能删原创。

用法
----
  python tools/check_transcript.py sources/05-播客转写/_medium
  python tools/check_transcript.py sources/05-播客转写/_medium --fix   # 生成 *._clean.txt
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 高频同音错词（左：ASR 常写；右：应为）。这张表要每轮扩。
HOMOPHONE = {
    "亮能": "量能",
    "很腰": "很妖",
    "注底": "筑底",
    "卫生区": "危险区",
    "一股近": "一股劲",
    "把旁边往上拉": "把盘面往上拉",
    "强硬机": "强硬的",
    "剪仓": "减仓",
    "检仓": "减仓",
    "创业版": "创业板",
    "上正": "上证",
    "上正指数": "上证指数",
    "警惧": "谨记",
    "警记": "谨记",
    "另名节目": "另一档节目",
    "科创五十": "科创50",
    "掌停": "涨停",
    "跌停板": "跌停板",
}

# 需要人工复核的（可能是对也可能是错，不自动替换）
SUSPECT = {
    "站在": "可能应为「站上」",
    "在注": "可能应为「在筑」",
}


def load_lines(p: Path):
    return p.read_text(encoding="utf-8").splitlines()


def body_lines(lines):
    """跳过元信息头部，返回 [(行号, 时间戳, 正文)]"""
    out = []
    started = False
    for i, ln in enumerate(lines, 1):
        if ln.strip() == "---":
            started = True
            continue
        if not started:
            continue
        m = re.match(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$", ln)
        if m:
            out.append((i, m.group(1), m.group(2)))
    return out


def count_trad(text, cc):
    """统计真正的繁体字（OpenCC 转换后会变的字符）"""
    conv = cc.convert(text)
    diffs = [(a, b) for a, b in zip(text, conv) if a != b]
    counts = {}
    for a, b in diffs:
        k = f"{a}→{b}"
        counts[k] = counts.get(k, 0) + 1
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="转写稿目录")
    ap.add_argument("--fix", action="store_true", help="生成 *._clean.txt（繁转简 + 同音修正）")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    d = Path(args.dir)
    if not d.is_absolute():
        d = ROOT / d
    files = sorted(
        f for f in d.glob("*.txt")
        if not f.name.startswith("_") and "._clean" not in f.name
    )
    if not files:
        print(f"{d} 下没有 .txt", file=sys.stderr)
        return 1

    try:
        from opencc import OpenCC

        cc = OpenCC("t2s")
    except ImportError:
        print("缺 opencc：pip install opencc-python-reimplemented", file=sys.stderr)
        return 1

    print(f"体检 {len(files)} 份转写稿  ({d})\n")
    print(f"{'文件':<44}{'段':>5}{'字数':>7}{'繁':>5}{'错词':>6}")
    print("-" * 70)

    grand_trad, grand_homo = {}, {}
    for f in files:
        lines = load_lines(f)
        body = body_lines(lines)
        text = "".join(b[2] for b in body)

        trad = count_trad(text, cc)
        for k, n in trad.items():
            grand_trad[k] = grand_trad.get(k, 0) + n
        homo_hits = 0
        for wrong, right in HOMOPHONE.items():
            c = text.count(wrong)
            if c:
                grand_homo[(wrong, right)] = grand_homo.get((wrong, right), 0) + c
                homo_hits += c

        print(
            f"{f.stem[:42]:<44}{len(body):>5}{len(text):>7}"
            f"{sum(trad.values()):>5}{homo_hits:>6}"
        )

        if args.fix:
            fixed, started = [], False
            for ln in lines:
                if ln.strip() == "---":
                    started = True
                    fixed.append(ln)
                    continue
                if started:
                    ln = cc.convert(ln)
                    for wrong, right in HOMOPHONE.items():
                        ln = ln.replace(wrong, right)
                fixed.append(ln)
            out = f.with_name(f.stem + "._clean.txt")
            out.write_text("\n".join(fixed) + "\n", encoding="utf-8")

    if args.fix:
        print("\n修正版 → *._clean.txt")

    print()
    tot_trad = sum(grand_trad.values())
    if tot_trad:
        print(f"繁体字 {tot_trad} 个，前 {args.top}：")
        items = sorted(grand_trad.items(), key=lambda x: -x[1])[: args.top]
        print("  " + "  ".join(f"{k}×{n}" for k, n in items))
    else:
        print("✅ 无繁体字")

    print()
    if grand_homo:
        print(f"同音错词 {sum(grand_homo.values())} 处：")
        for (wrong, right), n in sorted(grand_homo.items(), key=lambda x: -x[1]):
            print(f"  {wrong} → {right}  ×{n}")
        print("  ⚠️ 每轮转写后把新发现的错词加进 HOMOPHONE，否则会一直错下去")
    else:
        print("✅ 未命中已知同音错词（不代表没错，表还不全）")

    suspects = []
    for f in files:
        body = body_lines(load_lines(f))
        text = "".join(b[2] for b in body)
        for w, note in SUSPECT.items():
            n = text.count(w)
            if n:
                suspects.append((f.stem, w, n, note))
    if suspects:
        print(f"\n待人工复核 {len(suspects)} 项（不自动替换）：")
        for stem, w, n, note in suspects:
            print(f"  {stem[:36]:<38} 「{w}」×{n}  {note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
