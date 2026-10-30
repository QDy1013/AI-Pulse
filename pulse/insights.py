"""Derived views shared by the desktop window and the phone page:
Codex quota, spending budgets, per-day history and per-project totals."""
from __future__ import annotations

import re
import time
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

from .collector import APPS
from .pricing import DEFAULT_USD_TO_CNY, estimate_usd

HISTORY_DAYS = 30
PROJECT_LIMIT = 8
WARN_PERCENT = 80


def day_start(now):
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def month_start(now):
    return datetime.fromtimestamp(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def window_name(minutes):
    if minutes == 300:
        return '5 小时'
    if minutes == 10080:
        return '每周'
    if minutes == 1440:
        return '每日'
    return f'{minutes / 60:g} 小时'


def quota(data, now=None):
    """Codex usage-limit windows from the newest log snapshot.

    A window whose reset time has passed is reported as fully available, since
    Codex only writes a new snapshot on the next request."""
    now = now or time.time()
    snap = (data.get('Codex') or {}).get('limits')
    if not snap:
        return []
    out = []
    for w in snap['windows']:
        reset = w['resets_at']
        expired = bool(reset) and reset <= now
        used = 0.0 if expired else w['used']
        out.append({'name': f'Codex {window_name(w["minutes"])}', 'minutes': w['minutes'],
                    'used': used, 'left': max(0.0, 100.0 - used),
                    'resets_at': 0.0 if expired else reset, 'as_of': snap['t'], 'plan': snap['plan']})
    return out


def since(rows, start):
    """Rows (sorted by timestamp, as the collector returns them) at or after `start`."""
    return rows[bisect_left(rows, start, key=lambda r: r.timestamp):]


def spend_usd(data, start, rates=None):
    return sum(estimate_usd(r, rates)[0] for a in APPS for r in since((data.get(a) or {}).get('requests', []), start))


def budget(data, limits, rates=None, fx=DEFAULT_USD_TO_CNY, now=None):
    """Spending against the daily / monthly limits (CNY). Limits of 0 are off."""
    now = now or time.time()
    out = []
    for key, name, start in (('daily_cny', '今日预算', day_start(now)), ('monthly_cny', '本月预算', month_start(now))):
        try:
            limit = float((limits or {}).get(key) or 0)
        except (TypeError, ValueError):
            limit = 0.0
        if limit <= 0:
            continue
        spent = spend_usd(data, start, rates) * fx
        out.append({'key': key, 'name': name, 'spent': spent, 'limit': limit,
                    'pct': spent * 100 / limit, 'period': datetime.fromtimestamp(start).strftime('%Y-%m-%d')})
    return out


def history(data, apps=APPS, rates=None, now=None, days=HISTORY_DAYS):
    """Per-day cost and output for the last `days` local days, oldest first."""
    now = now or time.time()
    today = datetime.fromtimestamp(now).date()
    dates = [today - timedelta(days=days - 1 - i) for i in range(days)]
    # Local midnights (DST-safe) plus the next one; rows are bucketed by binary search.
    edges = [datetime.combine(d, datetime.min.time()).timestamp() for d in dates]
    edges.append(datetime.combine(today + timedelta(days=1), datetime.min.time()).timestamp())
    buckets = [{'usd': 0.0, 'output': 0, 'count': 0, 'apps': {}} for _ in dates]
    for a in apps:
        rows = (data.get(a) or {}).get('requests', [])
        # Rows are sorted by time: skip straight to the window.
        start = bisect_left(rows, edges[0], key=lambda r: r.timestamp)
        for r in rows[start:]:
            i = bisect_right(edges, r.timestamp) - 1
            if not 0 <= i < days:
                continue
            b = buckets[i]
            usd = estimate_usd(r, rates)[0]
            b['usd'] += usd
            b['output'] += r.output
            b['count'] += 1
            b['apps'][r.app] = b['apps'].get(r.app, 0.0) + usd
    return [dict(b, date=d.isoformat()) for d, b in zip(dates, buckets)]


def project_name(path):
    parts = [p for p in re.split(r'[\\/]+', path or '') if p]
    return parts[-1] if parts else ''


def projects(rows, rates=None, limit=PROJECT_LIMIT):
    """Totals per working directory, largest output first."""
    groups = {}
    for r in rows:
        g = groups.setdefault(r.project or '', {'path': r.project or '', 'output': 0, 'usd': 0.0, 'count': 0})
        g['output'] += r.output
        g['usd'] += estimate_usd(r, rates)[0]
        g['count'] += 1
    ranked = sorted(groups.values(), key=lambda g: (g['output'], g['usd']), reverse=True)[:limit]
    for g in ranked:
        g['name'] = project_name(g['path']) or '未记录目录'
    return ranked


def alerts(quota_rows, budget_rows):
    """(key, title, message) for every limit at or past its warning level.

    The key includes the period / reset time so each warning fires once per window."""
    out = []
    for b in budget_rows:
        if b['pct'] >= 100:
            out.append((f'{b["key"]}:{b["period"]}:over', f'{b["name"]}已超出',
                        f'已花费 ¥{b["spent"]:.2f}，超过 ¥{b["limit"]:g} 的预算。'))
        elif b['pct'] >= WARN_PERCENT:
            out.append((f'{b["key"]}:{b["period"]}:warn', f'{b["name"]}已用 {b["pct"]:.0f}%',
                        f'已花费 ¥{b["spent"]:.2f} / ¥{b["limit"]:g}。'))
    for q in quota_rows:
        if q['left'] <= 10 and q['resets_at']:
            reset = datetime.fromtimestamp(q['resets_at']).strftime('%m-%d %H:%M')
            out.append((f'quota:{q["minutes"]}:{q["resets_at"]:.0f}', f'{q["name"]}额度仅剩 {q["left"]:.0f}%',
                        f'将于 {reset} 重置。'))
    return out
