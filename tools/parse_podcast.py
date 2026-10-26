#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""parse_podcast.py — 从小宇宙播客页 HTML 里抽出剧集清单

为什么这么做
------------
小宇宙没有公开 API，但**播客主页的 HTML 里就嵌着完整的剧集 JSON**——
包含 `enclosure.url`（音频直链）、`duration`（秒）、`media.size`（字节数）、
`title`、`description`、`eid`。

所以不需要逐集打开 episode 页，也不需要登录。

用法
----
  python tools/parse_podcast.py research/_podcast_page.html
  python tools/parse_podcast.py research/_podcast_page.html --out research/episodes.json
  python tools/parse_podcast.py research/_podcast_page.html --list
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def extract_episodes(html: str):
    """从 HTML 里抽出 episodes 数组

    HTML 里是 Next.js 的 __NEXT_DATA__ 或内联 JSON。直接定位 "episodes":[
    然后做括号配平，比正则可靠。
    """
    episodes = []
    for m in re.finditer(r'"episodes"\s*:\s*\[', html):
        start = m.end() - 1  # 指向 [
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(html)):
            ch = html[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    blob = html[start : i + 1]
                    try:
                        arr = json.loads(blob)
                    except json.JSONDecodeError:
                        # 常见原因：JSON 里有未转义字符。跳过这一块
                        break
                    if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                        episodes.extend(arr)
                    break
    # 去重（同一页可能嵌多份）
    seen, uniq = set(), []
    for e in episodes:
        k = e.get("eid") or e.get("title")
        if k and k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def normalize(e):
    med = e.get("media") or {}
    enc = e.get("enclosure") or {}
    return {
        "eid": e.get("eid"),
        "title": e.get("title"),
        "date": (e.get("pubDate") or e.get("createdAt") or "")[:10],
        "duration_sec": e.get("duration"),
        "duration_min": round((e.get("duration") or 0) / 60, 1),
        "size_bytes": med.get("size"),
        "size_mb": round((med.get("size") or 0) / 1048576, 1),
        "mime": med.get("mimeType"),
        "audio_url": enc.get("url") or (med.get("source") or {}).get("url"),
        "description": (e.get("description") or "").strip(),
        "is_private": e.get("isPrivateMedia"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html", help="小宇宙播客页 HTML")
    ap.add_argument("--out", help="输出 JSON 路径")
    ap.add_argument("--list", action="store_true", help="打印清单")
    args = ap.parse_args()

    p = Path(args.html)
    if not p.is_absolute():
        p = ROOT / p
    html = p.read_text(encoding="utf-8", errors="ignore")

    raw = extract_episodes(html)
    eps = [normalize(e) for e in raw]
    eps = [e for e in eps if e["audio_url"]]

    if not eps:
        print("没抽到剧集。HTML 结构可能变了。", file=sys.stderr)
        return 1

    total_bytes = sum(e["size_bytes"] or 0 for e in eps)
    total_sec = sum(e["duration_sec"] or 0 for e in eps)

    print(f"抽到 {len(eps)} 集")
    print(f"  合计时长 {total_sec/3600:.2f} 小时（{total_sec/60:.0f} 分钟）")
    print(f"  合计体积 {total_bytes/1048576:.1f} MB")
    print(f"  平均每集 {total_sec/60/len(eps):.1f} 分钟 / {total_bytes/1048576/len(eps):.1f} MB")
    print(f"  格式 {sorted({e['mime'] for e in eps})}")
    print(f"  私密 {sum(1 for e in eps if e['is_private'])} 集")

    if args.list:
        print()
        print(f"{'日期':<12}{'时长':>7}{'体积':>9}  标题")
        for e in eps:
            print(
                f"{e['date']:<12}{e['duration_min']:>6.0f}m{e['size_mb']:>8.1f}M  {e['title']}"
            )

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(eps, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n→ {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
