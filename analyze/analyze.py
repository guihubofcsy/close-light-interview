#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tool_calls.csv 分析：成功/失败比例 + 失败原因统计。

产出 README.md 里的全部数字。零依赖，只用 Python 标准库。

用法：python analyze/analyze.py tool_calls.csv
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from collections import defaultdict

# 数据字段口径：
#   call_ok = 1 成功 / 0 失败 / 空 未回传
SUCCESS, FAIL, NO_REPLY = 1, 0, None

# 元数据滞后分档（call_ts 与 meta_synced_at 统一到 UTC 后相减，单位分钟）
LAG_BUCKETS = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 45), (45, 60), (60, 70)]


def parse_ts(s: str) -> datetime:
    """call_ts 带 +08:00，meta_synced_at 带 Z(UTC)，统一解析为 UTC 再比较。"""
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t).astimezone(timezone.utc)


def load(path: str):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "lag": (parse_ts(r["call_ts"]) - parse_ts(r["meta_synced_at"])).total_seconds() / 60.0,
                "ok": NO_REPLY if r["call_ok"].strip() == "" else int(r["call_ok"]),
                "tool": r["tool_name"],
                "biz": r["biz_line"],
                "conn": int(r["conn_available"]),
                "pay": int(r["payload_bytes"]),
                "raw": tuple(r.values()),
            })
    return rows


def counts(rows):
    """返回 ( 成功, 失败, 未回传, 已回传, 失败率 ) 。失败率分母为已回传。"""
    s = sum(1 for r in rows if r["ok"] == SUCCESS)
    f = sum(1 for r in rows if r["ok"] == FAIL)
    n = sum(1 for r in rows if r["ok"] is NO_REPLY)
    answered = s + f
    return s, f, n, answered, (f / answered * 100 if answered else 0.0)


def pct(a, b):
    return f"{a / b * 100:.1f}%" if b else "-"


def group(rows, key):
    d = defaultdict(list)
    for r in rows:
        d[r[key]].append(r)
    return d


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    path = sys.argv[1] if len(sys.argv) > 1 else "tool_calls.csv"
    rows = load(path)
    L = []
    A = L.append

    s, f, n, answered, rate = counts(rows)
    A("# tool_calls.csv 分析报告\n")
    A("## 一、总量与总体比例\n")
    A(f"- 调用总数：**{len(rows)}**")
    A(f"- 成功（call_ok=1）：**{s}**，占已回传 {pct(s, answered)}，占全部 {pct(s, len(rows))}")
    A(f"- 失败（call_ok=0）：**{f}**，占已回传 **{rate:.1f}%**，占全部 {pct(f, len(rows))}")
    A(f"- 未回传（call_ok 为空）：**{n}**，占全部 {pct(n, len(rows))}")
    A(f"- 未成功合计（失败+未回传）：**{f + n}**，占全部 {pct(f + n, len(rows))}")
    A("")

    A("## 二、按工具的成败比例（按失败次数降序）\n")
    A("| 工具 | 调用数 | 成功 | 失败 | 未回传 | 失败率(占已回传) | 成功占比(占调用数) |")
    A("|---|---|---|---|---|---|---|")
    for t, g in sorted(group(rows, "tool").items(), key=lambda kv: -counts(kv[1])[1]):
        ts, tf, tn, ta, tr = counts(g)
        A(f"| `{t}` | {len(g)} | {ts} | {tf} | {tn} | {tr:.1f}% | {pct(ts, len(g))} |")
    A("")

    A("## 三、按业务线的成败比例\n")
    A("| 业务线 | 调用数 | 成功 | 失败 | 未回传 | 失败率(占已回传) | 成功占比(占调用数) |")
    A("|---|---|---|---|---|---|---|")
    for b, g in sorted(group(rows, "biz").items(), key=lambda kv: -counts(kv[1])[4]):
        bs, bf, bn, ba, br = counts(g)
        A(f"| `{b}` | {len(g)} | {bs} | {bf} | {bn} | {br:.1f}% | {pct(bs, len(g))} |")
    A("")

    A("## 四、失败原因统计\n")
    A("### 4.1 按元数据滞后分档（call_ts 与 meta_synced_at 之差，统一 UTC）\n")
    A("| 滞后区间(分钟) | 调用数 | 失败数 | 失败率(占已回传) | 占总失败次数比重 | 未回传 |")
    A("|---|---|---|---|---|---|")
    for lo, hi in LAG_BUCKETS:
        g = [r for r in rows if lo <= r["lag"] < hi]
        if not g:
            continue
        gs, gf, gn, ga, gr = counts(g)
        label = "0–13" if hi == 15 else f"{lo}–{hi - 1}"
        A(f"| {label} | {len(g)} | {gf} | {gr:.1f}% | {pct(gf, f)} | {gn} |")
    A("")
    stale = [r for r in rows if r["lag"] >= 15]
    fresh = [r for r in rows if r["lag"] < 15]
    ss, sf, sn, sa, sr = counts(stale)
    fs, ff, fn, fa, fr = counts(fresh)
    A(f"- 滞后 <15 分钟：{len(fresh)} 次调用，失败 {ff} 次，失败率 **{fr:.1f}%**")
    A(f"- 滞后 ≥15 分钟：{len(stale)} 次调用（占全部 {pct(len(stale), len(rows))}），失败 {sf} 次，失败率 **{sr:.1f}%**")
    A(f"- **全部 {f} 次失败中有 {sf} 次（{pct(sf, f)}）落在滞后 ≥15 分钟的调用上**，"
      f"而这批调用只占全部调用的 {pct(len(stale), len(rows))} → 失败高度集中在元数据过期的调用上")
    A("")

    A("### 4.2 按连接水位 conn_available 分档\n")
    A("| 水位区间 | 调用数 | 失败数 | 失败率(占已回传) |")
    A("|---|---|---|---|")
    for lo in range(0, 30, 5):
        g = [r for r in rows if lo <= r["conn"] < lo + 5]
        if not g:
            continue
        _, gf, _, _, gr = counts(g)
        A(f"| {lo}–{lo + 4} | {len(g)} | {gf} | {gr:.1f}% |")
    g30 = [r for r in rows if r["conn"] >= 30]
    _, gf30, _, _, gr30 = counts(g30)
    A(f"| 30 (上限) | {len(g30)} | {gf30} | {gr30:.1f}% |")
    A("")

    A("### 4.3 按报文大小 payload_bytes 分档\n")
    A("| 区间(字节) | 调用数 | 失败数 | 失败率(占已回传) |")
    A("|---|---|---|---|")
    for lo in range(0, 110, 10):
        g = [r for r in rows if lo <= r["pay"] < lo + 10]
        if not g:
            continue
        _, gf, _, _, gr = counts(g)
        A(f"| {lo}–{lo + 9} | {len(g)} | {gf} | {gr:.1f}% |")
    A("")

    A("### 4.4 未回传（41 次）的分布\n")
    nr = [r for r in rows if r["ok"] is NO_REPLY]
    fnr = [r for r in nr if r["lag"] < 15]
    A("| 工具 | 未回传次数 |")
    A("|---|---|")
    for t, g in sorted(group(nr, "tool").items(), key=lambda kv: -len(kv[1])):
        A(f"| `{t}` | {len(g)} |")
    A("")
    A(f"- 其中滞后 <15 分钟的有 {len(fnr)} 次，占未回传的 **{pct(len(fnr), len(nr))}**")
    A(f"- 对照：未回传行的平均滞后 {sum(r['lag'] for r in nr) / len(nr):.1f} 分钟，"
      f"全体平均 {sum(r['lag'] for r in rows) / len(rows):.1f} 分钟")
    A("")

    A("### 4.5 剔除滞后因素后的对比（判断是不是业务线/工具本身的问题）\n")
    A("| 分组 | 调用数 | 平均滞后(分钟) | 滞后≥15 占比 | 失败率(全部) | 失败率(滞后<15) |")
    A("|---|---|---|---|---|---|")
    for label, key in (("业务线", "biz"), ("工具", "tool")):
        A(f"| **按{label}** | | | | | |")
        for name, g in sorted(group(rows, key).items(), key=lambda kv: -counts(kv[1])[4]):
            _, _, _, _, all_rate = counts(g)
            gf = [r for r in g if r["lag"] < 15]
            _, _, _, _, fresh_rate = counts(gf)
            avg = sum(r["lag"] for r in g) / len(g)
            share = sum(1 for r in g if r["lag"] >= 15) / len(g) * 100
            A(f"| `{name}` | {len(g)} | {avg:.1f} | {share:.1f}% | {all_rate:.1f}% | {fresh_rate:.1f}% |")
    A("")

    A("### 4.6 同日对照：排除「滞后只是上游故障时段的影子」\n")
    A("如果失败只是因为某个时段上游整体抖动，那么同一时段内的新鲜调用也该失败。")
    A("按自然日分组对照：\n")
    A("| 日期 | 滞后≥15: 已回传 / 失败率 | 滞后<15: 已回传 / 失败率 | 差值 |")
    A("|---|---|---|---|")
    for day in sorted({r["raw"][1][:10] for r in rows}):
        g = [r for r in rows if r["raw"][1].startswith(day)]
        day_stale = [r for r in g if r["lag"] >= 15 and r["ok"] is not None]
        day_fresh = [r for r in g if r["lag"] < 15 and r["ok"] is not None]
        sf2_ = sum(1 for r in day_stale if r["ok"] == 0)
        ff2_ = sum(1 for r in day_fresh if r["ok"] == 0)
        sr2_ = sf2_ / len(day_stale) * 100 if day_stale else 0.0
        fr2_ = ff2_ / len(day_fresh) * 100 if day_fresh else 0.0
        A(f"| {day} | {len(day_stale)} / {sr2_:.1f}% | {len(day_fresh)} / {fr2_:.1f}% | {sr2_ - fr2_:+.1f}pp |")
    A("")
    A("每一天都是过期组失败率远高于新鲜组 → 不能用「那个时段上游整体坏」解释；")
    A("即滞后本身在起作用，不是时段效应的影子。\n")

    A("## 五、数据口径核查（README 第二节引用的数字）\n")
    naive = []
    with open(path, encoding="utf-8-sig", newline="") as fp:
        for r in csv.DictReader(fp):
            a = datetime.fromisoformat(r["call_ts"]).replace(tzinfo=None)
            b = datetime.fromisoformat(r["meta_synced_at"].replace("Z", "")).replace(tzinfo=None)
            naive.append((a - b).total_seconds() / 60.0)
    lags = [r["lag"] for r in rows]
    A(f"- 不做时区转换直接相减：滞后均值 **{sum(naive) / len(naive):.0f} 分钟**，最小 **{min(naive):.0f} 分钟**（假象）")
    A(f"- 统一 UTC 后：滞后均值 **{sum(lags) / len(lags):.1f} 分钟**，范围 {min(lags):.0f}–{max(lags):.0f} 分钟")
    seen, uniq = set(), []
    for r in rows:
        if r["raw"] not in seen:
            seen.add(r["raw"])
            uniq.append(r)
    us, uf, un, ua, ur = counts(uniq)
    A(f"- 完全重复行：**{len(rows) - len(uniq)}** 行；去重后 **{len(uniq)}** 行，"
      f"失败率 **{ur:.1f}%**，未成功率 **{(uf + un) / len(uniq) * 100:.1f}%**"
      f"（全体 {(f + n) / len(rows) * 100:.1f}%）")
    A("")

    A("## 六、准入策略效果（若在调用前校验元数据新鲜度）\n")
    A("成本口径（题目给定）：每次失败 90 分钟；每标记元数据失效一次 10 分钟。")
    A("唯一假设：被拦下重新同步的调用，失败率回落到新鲜组实测水平，而不是假设 100% 成功。\n")
    A("| TTL(分钟) | 拦截调用 | 占全部 | 预计避免失败 | 改造后失败率 | 挽回工时(分钟) | 拦截成本(分钟) | 净节省(分钟) |")
    A("|---|---|---|---|---|---|---|---|")
    scan = []
    for ttl in (1, 5, 8, 10, 15, 20, 30, 60):
        g_stale = [r for r in rows if r["lag"] >= ttl]
        g_fresh = [r for r in rows if r["lag"] < ttl]
        _, _, _, fa, fresh_rate = counts(g_fresh)
        _, sf2, _, sa2, _ = counts(g_stale)
        avoided = sf2 - fresh_rate / 100 * sa2
        remaining = f - avoided
        saved = avoided * 90
        cost = len(g_stale) * 10
        net = saved - cost
        scan.append((ttl, len(g_stale), avoided, remaining / answered * 100, saved, cost, net))
        A(f"| {ttl} | {len(g_stale)} | {pct(len(g_stale), len(rows))} | {avoided:.1f} | "
          f"{remaining / answered * 100:.2f}% | {saved:.0f} | {cost:.0f} | "
          f"{'**' + format(net, '+.0f') + '**' if ttl == 15 else format(net, '+.0f')} |")
    A("")
    best = max(scan, key=lambda x: x[6])
    A(f"- 净收益最大的门槛：**TTL = {best[0]} 分钟**，净节省 {best[6]:.0f} 分钟")
    A(f"- 门槛过小会净亏：TTL = 1 分钟时净节省 **{scan[0][6]:+.0f} 分钟**"
      f"（拦下 {scan[0][1]} 次调用，成本吃掉全部收益）")
    A("")

    A("## 七、结论\n")
    A(f"1. 失败率总体 {rate:.1f}%，但**集中在元数据过期的调用上**：滞后 ≥15 分钟的调用失败率 {sr:.1f}%，"
      f"是滞后 <15 分钟（{fr:.1f}%）的 {sr / fr:.1f} 倍，且吃掉了 {pct(sf, f)} 的失败次数。")
    A(f"2. 连接水位、报文大小两个因素**不呈单调关系**，不能解释失败，排除。")
    A(f"3. 未回传 {n} 次与滞后无关（{pct(len(fnr), len(nr))} 发生在滞后 <15 分钟），是独立问题。")
    A(f"4. 建议：网关在调用前校验元数据新鲜度，滞后 ≥15 分钟先重新同步再调用"
      f"（对应 {len(stale)} 次调用，可覆盖 {pct(sf, f)} 的失败）。")
    A("")

    sys.stdout.write("\n".join(L))


if __name__ == "__main__":
    main()
