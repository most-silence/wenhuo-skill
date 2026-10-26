#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""download_podcast.py — 批量下载小宇宙播客音频

已验证
------
· 主页 HTML 里嵌着 enclosure.url 直链，无需登录、无需签名
· 格式 audio/mp4（.m4a），AAC 44100Hz 单声道
· Range 不支持也没关系，整文件下载即可

用法
----
  python tools/download_podcast.py --episodes research/episodes_page1.json --all
  python tools/download_podcast.py --episodes research/episodes_page1.json --sample 8
  python tools/download_podcast.py --episodes ... --eid 6ad0568f --eid 6acdaa26
"""

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sources" / "00-原始音频" / "podcast"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaoyuzhoufm.com/",
}


def fetch_one(ep, outdir: Path, retries=3):
    """下载一集。返回 (title, bytes, seconds, path|None)"""
    eid = ep["eid"][:8]
    date = ep.get("date") or "unknown"
    # 文件名带上标题，便于人看；去掉非法字符
    safe = "".join(c for c in (ep.get("title") or "") if c not in r'\/:*?"<>|').strip()
    fn = outdir / f"{date}_{eid}_{safe[:40]}.m4a"
    if fn.exists() and fn.stat().st_size > 10000:
        return (ep["title"], fn.stat().st_size, 0.0, fn, "已存在")

    last = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            req = urllib.request.Request(ep["audio_url"], headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            fn.write_bytes(data)
            return (ep["title"], len(data), time.time() - t0, fn, "ok")
        except Exception as ex:
            last = ex
            time.sleep(3 * (attempt + 1))
    return (ep["title"], 0, 0.0, None, f"失败: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", required=True, help="parse_podcast.py 输出的 JSON")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="均匀抽 N 集")
    ap.add_argument("--eid", action="append", default=[], help="指定 eid 前缀")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    src = Path(args.episodes)
    if not src.is_absolute():
        src = ROOT / src
    eps = json.loads(src.read_text(encoding="utf-8"))

    if args.eid:
        eps = [e for e in eps if any(e["eid"].startswith(x) for x in args.eid)]
    elif args.sample:
        step = max(1, len(eps) // args.sample)
        eps = eps[::step][: args.sample]
    elif not args.all:
        print("要么 --all，要么 --sample N，要么 --eid xxx")
        return 1

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"待下载 {len(eps)} 集，并发 {args.workers}")
    print(f"预计 {sum(e['size_mb'] for e in eps):.1f} MB\n")

    t0 = time.time()
    done = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(fetch_one, e, outdir): e for e in eps}
        for i, f in enumerate(as_completed(futs), 1):
            title, n, sec, path, status = f.result()
            mb = n / 1048576
            speed = mb / sec if sec > 0 else 0
            print(
                f"[{i:>2}/{len(eps)}] {status:6} {mb:>6.1f}MB "
                f"{speed:>5.1f}MB/s  {title[:34]}"
            )
            done.append((title, n, status, path))

    total = sum(d[1] for d in done)
    ok = sum(1 for d in done if d[2] in ("ok", "已存在"))
    print(f"\n完成 {ok}/{len(done)}，{total/1048576:.1f} MB，用时 {time.time()-t0:.0f}s")

    manifest = outdir / "_manifest.json"
    rows = [
        {"title": t, "bytes": n, "status": s, "file": p.name if p else None}
        for t, n, s, p in done
    ]
    manifest.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"清单 → {manifest}")
    return 0 if ok == len(done) else 1


if __name__ == "__main__":
    sys.exit(main())
