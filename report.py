"""Minimal HTML + CSV renderer for the ranked output."""
from pathlib import Path

import pandas as pd


_CSS = (
    "* { box-sizing: border-box; }"
    " body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;"
    " font-size: 14px; padding: 12px; max-width: 100%; margin: 0;"
    " color: #222; background: #fff; }"
    " table { border-collapse: collapse; width: 100%; max-width: 100%; }"
    " th, td { padding: 6px 8px; border-bottom: 1px solid #eee; text-align: left;"
    " vertical-align: top; }"
    " th { background: #f7f7f7; font-weight: 600; }"
    " td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }"
    " td.colored { color: #1a1a1a; }"  # composite cell text always dark on colored bg
    " .header { margin-bottom: 8px; color: #444; }"
    " @media (prefers-color-scheme: dark) {"
    "   body { color: #e6e6e6; background: #121212; }"
    "   th { background: #1f1f1f; }"
    "   th, td { border-bottom-color: #2a2a2a; }"
    "   .header { color: #aaa; }"
    " }"
)


def _composite_color(v: float) -> str:
    if v >= 0.5:
        return "#2ecc71"
    if v >= 0.1:
        return "#a9dfbf"
    if v <= -0.5:
        return "#e74c3c"
    if v <= -0.1:
        return "#f5b7b1"
    return ""


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_weights(weights: dict) -> str:
    parts = [f"{k.title()}={v:.2f}" for k, v in weights.items()]
    return ", ".join(parts) if parts else "(none)"


def render(ranked_df: pd.DataFrame, names: dict, factors_used: dict) -> str:
    """Return HTML string."""
    weights = factors_used.get("weights", {})
    header = f"Weights: {_format_weights(weights)}"

    rows_html = []
    for ticker, row in ranked_df.iterrows():
        rank_val = row.get("rank")
        rank = int(rank_val) if pd.notna(rank_val) else ""
        sector = _escape(row.get("sector") or "")
        comp_val = row.get("composite")
        composite = float(comp_val) if pd.notna(comp_val) else 0.0
        color = _composite_color(composite)
        cls = "num colored" if color else "num"
        style = f' style="background:{color}"' if color else ""
        name = _escape(names.get(ticker, ticker))
        rows_html.append(
            "<tr>"
            f'<td class="num">{rank}</td>'
            f"<td>{_escape(ticker)}</td>"
            f"<td>{name}</td>"
            f"<td>{sector}</td>"
            f'<td class="{cls}"{style}>{composite:.3f}</td>'
            "</tr>"
        )

    return (
        "<!doctype html>"
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        "<title>M/Q/V Ranking</title>"
        f"<style>{_CSS}</style>"
        "</head><body>"
        f'<div class="header">{_escape(header)}</div>'
        "<table>"
        "<thead><tr>"
        "<th>Rank</th><th>Ticker</th><th>Company</th><th>Sector</th><th>Composite</th>"
        "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table></body></html>"
    )


def write_report(html: str, path: str) -> None:
    """Write html to path, creating parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")


def write_csv(ranked_df: pd.DataFrame, path: str) -> None:
    """Write the full ranked_df to CSV (all columns, ticker as index)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ranked_df.to_csv(p, index=True)
