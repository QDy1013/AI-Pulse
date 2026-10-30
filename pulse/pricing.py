"""API quota & cost estimation ($ USD equivalent + RMB conversion) per request."""
from __future__ import annotations

DEFAULT_USD_TO_CNY = 7.15

# (uncached_input_per_1m, cached_input_per_1m, output_per_1m, cache_write_per_1m) in USD.
# Matched in order by case-insensitive substring against request.model.
DEFAULT_MODEL_RATES: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    # OpenAI / Codex
    ('gpt-6-astra', (10.0, 1.0, 50.0, 10.0)),
    ('gpt-6.1-sol', (2.0, 0.20, 10.0, 2.0)),
    ('gpt-6.1-terra', (1.0, 0.05, 5.0, 1.0)),
    ('gpt-6-luna', (0.10, 0.01, 0.50, 0.10)),
    ('gpt-5.6-sol', (2.0, 0.20, 10.0, 2.0)),
    ('gpt-5.6-terra', (1.0, 0.05, 5.0, 1.0)),
    ('gpt-5.3-codex', (2.0, 0.20, 10.0, 2.0)),
    ('gpt-5.5', (2.0, 0.20, 10.0, 2.0)),
    ('codex-auto-review', (0.40, 0.04, 1.60, 0.40)),
    ('gpt-5.4-mini', (0.40, 0.04, 1.60, 0.40)),
    ('gpt-5-mini', (0.30, 0.03, 1.20, 0.30)),
    ('gpt-4.1-mini', (0.40, 0.10, 1.60, 0.40)),
    ('gpt-4.1', (2.0, 0.50, 8.0, 2.0)),
    ('gpt-4o-mini', (0.15, 0.075, 0.60, 0.15)),
    ('gpt-4o', (2.50, 1.25, 10.0, 2.50)),
    ('o3', (2.0, 0.50, 8.0, 2.0)),
    ('o4-mini', (1.10, 0.275, 4.40, 1.10)),
    # Anthropic / Claude
    ('claude-opus-5-5', (4.0, 0.20, 20.0, 8.0)),
    ('claude opus 5.5', (4.0, 0.20, 20.0, 8.0)),
    ('claude-opus', (5.0, 0.50, 25.0, 6.25)),
    ('claude opus', (5.0, 0.50, 25.0, 6.25)),
    ('claude-sonnet', (3.0, 0.30, 15.0, 3.75)),
    ('claude sonnet', (3.0, 0.30, 15.0, 3.75)),
    ('claude-haiku-5-5', (0.10, 0.01, 0.50, 0.125)),
    ('claude haiku 5.5', (0.10, 0.01, 0.50, 0.125)),
    ('claude-haiku', (0.80, 0.08, 4.0, 1.0)),
    ('claude haiku', (0.80, 0.08, 4.0, 1.0)),
    # Google / Gemini (Antigravity)
    ('gemini 4 argon', (2.0, 0.10, 10.0, 2.0)),
    ('gemini-4-argon', (2.0, 0.10, 10.0, 2.0)),
    ('gemini 3.8 flash', (0.75, 0.075, 3.75, 0.75)),
    ('gemini-3.8-flash', (0.75, 0.075, 3.75, 0.75)),
    ('gemini 3 pro', (1.25, 0.125, 10.0, 1.25)),
    ('gemini-3-pro', (1.25, 0.125, 10.0, 1.25)),
    ('gemini 2.5 pro', (1.25, 0.125, 10.0, 1.25)),
    ('gemini-2.5-pro', (1.25, 0.125, 10.0, 1.25)),
    ('gemini', (0.50, 0.05, 2.50, 0.50)),
    # DeepSeek / Moonshot / Zhipu / Qwen
    ('deepseek-v4-pro', (0.30, 0.006, 1.20, 0.30)),
    ('deepseek-v4-flash-vision', (0.30, 0.006, 1.20, 0.30)),
    ('deepseek-v4.1', (0.15, 0.003, 0.60, 0.15)),
    ('deepseek-v4', (0.15, 0.003, 0.60, 0.15)),
    ('deepseek-reasoner', (0.55, 0.14, 2.19, 0.55)),
    ('deepseek', (0.15, 0.003, 0.60, 0.15)),
    ('kimi-k3.1-pro', (2.0, 0.20, 10.0, 2.0)),
    ('kimi', (2.0, 0.20, 10.0, 2.0)),
    ('glm-5.3-flash', (0.15, 0.03, 0.50, 0.15)),
    ('glm', (0.15, 0.03, 0.50, 0.15)),
    ('qwen', (0.40, 0.08, 1.20, 0.40)),
)

# App-level fallback if an unknown model name has no match.
APP_FALLBACK_RATES: dict[str, tuple[float, float, float, float]] = {
    'Codex': (2.0, 0.20, 10.0, 2.0),
    'Claude': (3.0, 0.30, 15.0, 3.75),
    'Reasonix': (0.15, 0.003, 0.60, 0.15),
    'Antigravity': (2.0, 0.10, 10.0, 2.0),
    'WorkBuddy': (0.15, 0.003, 0.60, 0.15),
}


def resolve_rate(app: str, model: str, custom_rates: dict | None = None) -> tuple[float, float, float, float]:
    low = (model or '').lower()
    if custom_rates:
        for pattern, triple in custom_rates.items():
            if pattern.lower() in low and isinstance(triple, (list, tuple)) and len(triple) >= 3:
                inp, cached, out = float(triple[0]), float(triple[1]), float(triple[2])
                cw = float(triple[3]) if len(triple) >= 4 else inp
                return (inp, cached, out, cw)
    for pattern, rate in DEFAULT_MODEL_RATES:
        if pattern in low:
            return rate
    return APP_FALLBACK_RATES.get(app, (1.0, 0.10, 5.0, 1.0))


def split_input_tokens(req) -> tuple[int, int, int]:
    """Return (uncached_input, cached_read, cache_write) tokens for billing."""
    cw = max(0, getattr(req, 'cache_write', 0) or 0)
    cached = max(0, req.cached or 0)
    # Antigravity stores uncached input in field 2 and cache reads separately in field 5.
    if req.app == 'Antigravity':
        return (max(0, req.input or 0), cached, cw)
    uncached = max(0, (req.input or 0) - cached - cw)
    return (uncached, cached, cw)


def estimate_usd(req, custom_rates: dict | None = None) -> tuple[float, float]:
    """Return (actual_usd, uncached_list_usd) for a Request.

    Note: reasoning tokens are already included inside output tokens across all
    supported schemas, so output is billed once without double-adding reasoning.
    """
    inp_rate, cache_rate, out_rate, cw_rate = resolve_rate(req.app, req.model, custom_rates)
    uncached, cached, cw = split_input_tokens(req)
    out = max(0, req.output or 0)
    full_usd = ((uncached + cached + cw) * inp_rate + out * out_rate) / 1_000_000
    reported = getattr(req, 'cost_usd', None)
    has_override = bool(custom_rates and any(p.lower() in (req.model or '').lower() for p in custom_rates))
    if reported is not None and reported >= 0 and not has_override:
        return (reported, max(reported, full_usd))
    actual_usd = (uncached * inp_rate + cached * cache_rate + cw * cw_rate + out * out_rate) / 1_000_000
    return (actual_usd, full_usd)


def format_usd(amount: float) -> str:
    if amount >= 100:
        return f'${amount:,.1f}'
    if amount >= 1:
        return f'${amount:,.2f}'
    if amount >= 0.01:
        return f'${amount:.3f}'
    if amount > 0:
        return f'${amount:.4f}'
    return '$0.00'


def format_cny(amount: float) -> str:
    if amount >= 100:
        return f'¥{amount:,.1f}'
    if amount >= 1:
        return f'¥{amount:,.2f}'
    if amount >= 0.01:
        return f'¥{amount:.2f}'
    if amount > 0:
        return f'¥{amount:.3f}'
    return '¥0.00'


def parse_custom_rates(text: str) -> dict[str, list[float]]:
    """Parse lines like 'gpt-6.1-sol = 2.0, 0.2, 10.0' ($/1M: input, cached, output[, cache_write])."""
    rates: dict[str, list[float]] = {}
    for line in text.splitlines():
        name, sep, rhs = line.partition('=')
        name = name.strip()
        if not sep or not name:
            continue
        parts = [p.strip() for p in rhs.split(',') if p.strip()]
        if len(parts) < 3:
            continue
        try:
            nums = [max(0.0, float(x)) for x in parts[:4]]
        except ValueError:
            continue
        rates[name] = nums
    return rates


def format_custom_rates(rates: dict) -> str:
    lines = []
    for k, vals in rates.items():
        if isinstance(vals, (list, tuple)) and len(vals) >= 3:
            joined = ', '.join(f'{float(v):g}' for v in vals[:4])
            lines.append(f'{k} = {joined}')
    return '\n'.join(lines)
