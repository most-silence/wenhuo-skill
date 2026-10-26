#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
眼哥素材转写器 —— faster-whisper + PyAV（无需系统 ffmpeg）

用法:
    python transcribe.py --input "路径或通配符" --model small --outdir 输出目录

设计要点:
  1. 铁律: 转写稿不润色。这里只做语音转文字，不做任何改写/总结。
  2. 带时间戳输出 [HH:MM:SS]，供 Q1 原文溯源定位到「第几期第几分钟」。
  3. initial_prompt 注入股票术语，降低 ASR 把「隆基绿能」「中际旭创」听错的概率。
  4. 全程 UTF-8 写文件，避免 Windows 控制台编码问题。
"""
import argparse
import glob
import os
import sys
import time

# 领域提示词：把常见股市术语喂给解码器，显著降低专有名词错误率
DOMAIN_PROMPT = (
    "以下是一档关于中国A股的股票节目，说话人是博主「眼哥」，节目叫「眼哥股市会」。"
    "口头禅：「我是你的眼，带你领略股市的变化」「股市有风险，投资需谨慎」。"
    "经常提到：小宇宙、微博、抖音、B站。"
    "内容涉及大盘、指数、板块、个股、均线、成交量、换手率、做T、龙头、涨停、跌停、"
    "支撑位、压力位、缩量、放量、主力、游资、北向资金、沪深300、创业板、科创板、"
    "新能源、半导体、军工、消费、医药、券商、银行、地产等术语。"
)


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="媒体文件路径或通配符")
    ap.add_argument("--outdir", required=True, help="转写稿输出目录")
    ap.add_argument("--model", default="small", help="模型: tiny/base/small/medium/large-v3")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument("--limit-min", type=float, default=0.0, help="只转写前 N 分钟（调试用）")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    files = sorted(glob.glob(args.input))
    if not files:
        print(f"[ERR] no file matched: {args.input}")
        sys.exit(1)

    os.makedirs(args.outdir, exist_ok=True)

    t0 = time.time()
    print(f"[model] loading {args.model} ({args.device}/{args.compute_type}) ...", flush=True)
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print(f"[model] ready in {time.time() - t0:.1f}s", flush=True)

    for idx, path in enumerate(files, 1):
        base = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(args.outdir, base + ".txt")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            print(f"[{idx}/{len(files)}] SKIP (exists): {base}", flush=True)
            continue

        print(f"[{idx}/{len(files)}] transcribing: {base}", flush=True)
        started = time.time()

        segments, info = model.transcribe(
            path,
            language=args.language,
            beam_size=args.beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            initial_prompt=DOMAIN_PROMPT,
            condition_on_previous_text=False,   # 长音频防复读死循环
            temperature=[0.0, 0.2, 0.4],
        )

        duration = info.duration
        if args.limit_min > 0:
            duration = min(duration, args.limit_min * 60)

        lines = []
        n = 0
        for seg in segments:
            if seg.start > duration:
                break
            text = seg.text.strip()
            if not text:
                continue
            lines.append(f"[{fmt_ts(seg.start)}] {text}")
            n += 1
            if n % 50 == 0:
                print(f"    ... {fmt_ts(seg.end)} / {fmt_ts(duration)}", flush=True)

        header = (
            f"# 元信息\n"
            f"来源文件：{os.path.basename(path)}\n"
            f"音频时长：{fmt_ts(duration)}\n"
            f"转写工具：faster-whisper {args.model} ({args.compute_type}, {args.device})\n"
            f"转写时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"说话人：眼哥（未做说话人分离）\n"
            f"---\n\n"
        )
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(header)
            f.write("\n".join(lines))
            f.write("\n")

        elapsed = time.time() - started
        speed = duration / elapsed if elapsed > 0 else 0
        print(
            f"    OK -> {os.path.basename(out_path)} | {n} segments | "
            f"{elapsed / 60:.1f} min elapsed | {speed:.1f}x realtime",
            flush=True,
        )

    print(f"[done] total {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
