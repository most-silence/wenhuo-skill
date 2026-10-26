#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_names.py — 候选框架名的撞名体检

检查四个层面：
  1. PyPI    — 包名是否被占
  2. npm     — 包名是否被占
  3. GitHub  — 仓库名搜索（未认证 API 限流 10 次/分，全程 sleep）
  4. 结果里有没有「同名且同领域」的（比撞字更严重的是撞领域）

候选（中英配对的拼音 handle）：
  taozhen   淘真   —— 沙里淘金 + 去伪存真
  pisha     披沙   —— 披沙拣金
  xuanzhu   玄珠   —— 庄子遗珠寓言
  cunzhen   存真   —— 去伪存真
  gouxuan   钩玄   —— 提要钩玄
  chunqing  纯青   —— 炉火纯青
  stillcraft — 蒸馏工艺（英造词）
  sanmei    三昧   —— 之前的候选，一并测
"""
import json
import sys
import time
import urllib.request

UA = {"User-Agent": "name-check/1.0",
      "Accept": "application/vnd.github+json"}

CANDS = [
    ("taozhen", "淘真", "沙里淘金 + 去伪存真"),
    ("pisha", "披沙", "披沙拣金"),
    ("xuanzhu", "玄珠", "庄子·天地：黄帝游赤水，遗其玄珠"),
    ("cunzhen", "存真", "去伪存真"),
    ("gouxuan", "钩玄", "韩愈：提要钩玄"),
    ("chunqing", "纯青", "炉火纯青"),
    ("stillcraft", "静工", "still(蒸馏器)+craft"),
    ("sanmei", "三昧", "得其三昧"),
]


def get(url, t=20):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=t).read().decode("utf-8", "ignore"))


def check_pypi(h):
    try:
        get(f"https://pypi.org/pypi/{h}/json")
        return "❌ 已被占用"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "✓ 空闲"
        return f"? HTTP {e.code}"
    except Exception as ex:
        return f"? {type(ex).__name__}"


def check_npm(h):
    try:
        get(f"https://registry.npmjs.org/{h}")
        return "❌ 已被占用"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "✓ 空闲"
        return f"? HTTP {e.code}"
    except Exception as ex:
        return f"? {type(ex).__name__}"


def check_gh_exact(h):
    try:
        d = get(f"https://api.github.com/search/repositories?q={h}+in:name")
        items = d.get("items", [])[:5]
        n = d.get("total_count", 0)
        hits = [f"{i['full_name']}({i.get('stargazers_count',0)}★)" for i in items]
        return n, hits
    except Exception as ex:
        return None, [f"ERR {type(ex).__name__}"]


def main():
    print(f"{'handle':<12}{'中文':<6}{'PyPI':<10}{'npm':<10}  GitHub in:name")
    print("-" * 88)
    for h, zh, why in CANDS:
        p = check_pypi(h)
        n = check_npm(h)
        cnt, top = check_gh_exact(h)
        gh = f"{cnt} 个仓库" if cnt is not None else "ERR"
        print(f"{h:<12}{zh:<6}{p:<10}{n:<10}  {gh}")
        for t in top:
            print(f"{'':<38}    · {t}")
        time.sleep(7)  # 未认证 GitHub 搜索 10 次/分钟
    print("\n注：GitHub 搜索有 7 秒节流；total_count=0 才算干净。")


if __name__ == "__main__":
    sys.exit(main())
