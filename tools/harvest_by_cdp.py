#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""harvest_by_cdp.py — 用本机 Edge/Chrome 自动滚动，把播客全部剧集收下来

思路
----
拿不到 378 期的唯一障碍是分页接口要鉴权。但**浏览器能登录态、能签名**。
所以不做接口逆向，直接驱动本机浏览器：

  1. 以 --remote-debugging-port 启动一个**独立 profile** 的 Edge/Chrome
     （不碰你日常浏览器的数据和窗口）
  2. 打开播客页 → 循环滚动到底 → 页面自己调它的 API 加载下一页
  3. 从 window.__NEXT_DATA__ 里把**已渲染的全部剧集**读出来
     （页面滚动加载后，客户端数据会合并进去）
  4. 导出 JSON：eid / title / pubDate / enclosure.url

依赖：pip install playwright   （用 channel 直连本机 Edge/Chrome，
      不下 playwright 自带浏览器，省 ~400MB 流量）

首次运行需要你**人工过一道墙**：
  脚本会打开浏览器停在播客页——如果页面有验证码/风控，你手动滑一下，
  然后回车，脚本接手滚动。之后全程无人值守。

用法
----
  python tools/harvest_by_cdp.py                # 滚动到无新增为止
  python tools/harvest_by_cdp.py --max 500      # 最多滚 500 屏（默认）
  python tools/harvest_by_cdp.py --browser edge # 默认 auto 探测
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "episodes_all.json"
PID_URL = "https://www.xiaoyuzhoufm.com/podcast/6860f13d09b4c8a7b539a3f8"

EXTRACT_JS = """
() => {
  const out = [];
  const seen = new Set();
  const walk = (node) => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (node.eid && node.title && !seen.has(node.eid)) {
      const enc = node.enclosure && node.enclosure.url;
      if (enc) {
        seen.add(node.eid);
        out.push({
          eid: node.eid,
          title: node.title,
          date: (node.pubDate || '').slice(0, 10),
          duration_sec: node.duration || null,
          size_bytes: node.media ? node.media.size : null,
          audio_url: enc,
        });
      }
    }
    Object.values(node).forEach(walk);
  };
  // 优先读 Next.js 客户端数据（含滚动合并后的完整列表）
  const nd = document.querySelector('#__NEXT_DATA__');
  if (nd) { try { walk(JSON.parse(nd.textContent)); } catch (e) {} }
  // 兜底：扫 DOM 上 React 内部 props
  if (out.length === 0) {
    document.querySelectorAll('a[href*="/episode/"]').forEach(a => {
      const k = Object.keys(a).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactProps$'));
      if (k) walk(a[k]);
    });
  }
  return out;
}
"""


def find_browser(prefer):
    cands = {
        "edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
    }
    import os

    order = [prefer] if prefer != "auto" else ["edge", "chrome"]
    for name in order:
        for p in cands.get(name, []):
            if os.path.exists(p):
                return name, p
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=500, help="最多滚动次数")
    ap.add_argument("--browser", default="auto", choices=["auto", "edge", "chrome"])
    ap.add_argument("--settle", type=float, default=1.6, help="每屏等待秒")
    ap.add_argument("--port", type=int, default=9333)
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("先装：pip install playwright （约 40MB，不下载浏览器）", file=sys.stderr)
        return 1

    name, exe = find_browser(args.browser)
    if not exe:
        print("没找到 Edge/Chrome", file=sys.stderr)
        return 1
    print(f"浏览器: {name} @ {exe}")

    profile = ROOT / "tools" / ".cdp_profile"
    profile.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=exe,
            headless=False,  # 首跑要人工过一次验证码，故意看得见
            args=[
                f"--remote-debugging-port={args.port}",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1280, "height": 1600},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(PID_URL, wait_until="domcontentloaded")

        print("\n>>> 如果页面有验证/提示，手动处理一下；准备好后按回车 <<<")
        try:
            input()
        except EOFError:
            pass

        total, stable = 0, 0
        t0 = time.time()
        for i in range(args.max):
            page.mouse.wheel(0, 2200)
            time.sleep(args.settle)
            eps = page.evaluate(EXTRACT_JS)
            n = len(eps)
            if n == total:
                stable += 1
            else:
                stable = 0
                total = n
            if i % 5 == 0 or stable in (2, 5, 10):
                print(f"  [{i:3d} 屏 / {time.time()-t0:5.0f}s] 已收 {n} 集")
            # 连续 6 屏无新增 → 到底了
            if stable >= 6 and total > 15:
                print(f"  连续 {stable} 屏无新增，判定到底")
                break

        eps = page.evaluate(EXTRACT_JS)
        ctx.close()

    print(f"\n共收 {len(eps)} 集")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "harvested_at": datetime.now().isoformat(timespec="seconds"),
                "method": "CDP scroll on client-side data",
                "count": len(eps),
                "episodes": eps,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"写入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
