"""Build the HTML digest and send it via Gmail SMTP (App Password)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, BaseLoader, select_autoescape

from .config import Config
from .models import Movement, Signal

log = logging.getLogger("cardstock.email")

DISCLAIMER = (
    "Signals are screening suggestions from daily price snapshots, not guarantees. "
    "Confirm condition and authenticity before buying or selling — market price is not "
    "the price of any one specific card."
)

TEMPLATE = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color:#1a1a1a; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  h2 { font-size: 15px; margin: 22px 0 6px; border-bottom: 2px solid #eee; padding-bottom:4px; }
  .sub { color:#777; font-size:12px; margin-bottom: 8px;}
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid #eee; }
  th { background:#fafafa; }
  .up { color:#137333; } .down { color:#b3261e; }
  .pill { display:inline-block; padding:1px 7px; border-radius:10px; font-size:11px; font-weight:600; }
  .buy { background:#e6f4ea; color:#137333; }
  .avoid { background:#fce8e6; color:#b3261e; }
  .sell { background:#fef7e0; color:#9a6700; }
  .thin { color:#999; font-size:11px; }
  .none { color:#999; font-style: italic; font-size:13px; }
  .foot { color:#999; font-size:11px; margin-top:24px; border-top:1px solid #eee; padding-top:8px;}
</style></head><body>

<h1>{{ subject_prefix }} — {{ date }}</h1>
<div class="sub">Watchlist: {{ watchlist|length }} cards · tracked via {{ source }} (TCGplayer market, USD)</div>

{% if summary %}
<h2>📊 Business snapshot (CAD)</h2>
<table>
  <tr><th>Spent</th><th>Budget left</th><th>Realized profit</th><th>Holdings (mkt / cost)</th><th>Below-market</th></tr>
  <tr>
    <td>CA${{ '%.2f'|format(summary.spent) }}<br><span class="thin">{{ summary.n_held }} held · {{ summary.n_sold }} sold</span></td>
    <td><b>CA${{ '%.2f'|format(summary.budget_left) }}</b></td>
    <td class="{{ 'up' if summary.realized_profit>=0 else 'down' }}">CA${{ '%.2f'|format(summary.realized_profit) }}</td>
    <td>{% if summary.holdings_market_cad is not none %}CA${{ '%.2f'|format(summary.holdings_market_cad) }} / CA${{ '%.2f'|format(summary.holdings_cost) }}{% else %}—{% endif %}</td>
    <td class="{{ 'up' if (summary.below_market_savings or 0)>=0 else 'down' }}">{% if summary.below_market_savings is not none %}CA${{ '%.2f'|format(summary.below_market_savings) }}{% else %}—{% endif %}</td>
  </tr>
</table>
{% endif %}

{% macro pct(v) %}{% if v is not none %}<span class="{{ 'up' if v>0 else 'down' }}">{{ '%+.1f'|format(v*100) }}%</span>{% else %}—{% endif %}{% endmacro %}
{% macro money(v) %}{% if v is not none %}${{ '%.2f'|format(v) }}{% else %}—{% endif %}{% endmacro %}

<h2>🟢 BUY candidates ({{ buys|length }})</h2>
{% if buys %}<table><tr><th>Card</th><th>Now</th><th>Max buy</th><th>Why</th></tr>
{% for s in buys %}<tr><td>{{ s.name }}</td><td>{{ money(s.current) }}</td><td>{{ money(s.max_buy) }}</td><td>{{ s.reason }}</td></tr>{% endfor %}
</table>{% else %}<div class="none">No buy candidates today.</div>{% endif %}

<h2>🔴 SELL / take-profit ({{ sells|length }})</h2>
{% if sells %}<table><tr><th>Card</th><th>Now</th><th>Why</th></tr>
{% for s in sells %}<tr><td>{{ s.name }}</td><td>{{ money(s.current) }}</td><td>{{ s.reason }}</td></tr>{% endfor %}
</table>{% else %}<div class="none">Nothing to take profit on today.</div>{% endif %}

<h2>⚠️ AVOID / overheated ({{ avoids|length }})</h2>
{% if avoids %}<table><tr><th>Card</th><th>Now</th><th>Why</th></tr>
{% for s in avoids %}<tr><td>{{ s.name }}</td><td>{{ money(s.current) }}</td><td>{{ s.reason }}</td></tr>{% endfor %}
</table>{% else %}<div class="none">Nothing flagged as overheated.</div>{% endif %}

<h2>📈 Top movers up</h2>
{% if movers_up %}<table><tr><th>Card</th><th>Now</th><th>Day</th><th>vs 7d</th><th>vs 30d</th></tr>
{% for m in movers_up %}<tr><td>{{ m.name }}{% if m.thin %} <span class="thin">thin</span>{% endif %}</td><td>{{ money(m.current) }}</td><td>{{ pct(m.pct_day) }}</td><td>{{ pct(m.pct_7d) }}</td><td>{{ pct(m.pct_30d) }}</td></tr>{% endfor %}
</table>{% else %}<div class="none">Not enough history yet (need 2+ runs).</div>{% endif %}

<h2>📉 Top movers down</h2>
{% if movers_down %}<table><tr><th>Card</th><th>Now</th><th>Day</th><th>vs 7d</th><th>vs 30d</th></tr>
{% for m in movers_down %}<tr><td>{{ m.name }}{% if m.thin %} <span class="thin">thin</span>{% endif %}</td><td>{{ money(m.current) }}</td><td>{{ pct(m.pct_day) }}</td><td>{{ pct(m.pct_7d) }}</td><td>{{ pct(m.pct_30d) }}</td></tr>{% endfor %}
</table>{% else %}<div class="none">Not enough history yet (need 2+ runs).</div>{% endif %}

<h2>👀 Watchlist summary</h2>
{% if watchlist %}<table><tr><th>Card</th><th>Now</th><th>30d avg</th><th>vs 30d</th><th>Held</th></tr>
{% for m in watchlist %}<tr><td>{{ m.name }}{% if m.thin %} <span class="thin">thin</span>{% endif %}</td><td>{{ money(m.current) }}</td><td>{{ money(m.avg30) }}</td><td>{{ pct(m.pct_30d) }}</td><td>{{ '✓' if m.owned else '' }}</td></tr>{% endfor %}
</table>{% else %}<div class="none">Watchlist is empty.</div>{% endif %}

<div class="foot">{{ disclaimer }}</div>
</body></html>
"""


def build_html(
    cfg: Config,
    date: str,
    source: str,
    signals: List[Signal],
    movers_up: List[Movement],
    movers_down: List[Movement],
    watchlist: List[Movement],
    summary=None,
) -> str:
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape(["html"]))
    tmpl = env.from_string(TEMPLATE)
    return tmpl.render(
        subject_prefix=cfg.get("email.subject_prefix", "[Card Squad] Daily Digest"),
        date=date,
        source=source,
        summary=summary,
        buys=[s for s in signals if s.kind == "BUY"],
        sells=[s for s in signals if s.kind == "SELL"],
        avoids=[s for s in signals if s.kind == "AVOID"],
        movers_up=movers_up,
        movers_down=movers_down,
        watchlist=watchlist,
        disclaimer=DISCLAIMER,
    )


def send_email(cfg: Config, subject: str, html: str) -> bool:
    """Send via Gmail SMTP over SSL. Returns True on success."""
    sender = cfg.gmail_address
    password = cfg.gmail_app_password
    to_addr = cfg.digest_to
    if not (sender and password and to_addr):
        log.error("email not configured (GMAIL_ADDRESS / GMAIL_APP_PASSWORD / DIGEST_TO). Skipping send.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.attach(MIMEText("HTML email — view in an HTML-capable client.", "plain"))
    msg.attach(MIMEText(html, "html"))

    host = cfg.get("email.smtp_host", "smtp.gmail.com")
    port = int(cfg.get("email.smtp_port", 465))
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(host, port, context=ctx) as server:
            server.login(sender, password)
            server.sendmail(sender, [to_addr], msg.as_string())
        log.info("digest emailed to %s", to_addr)
        return True
    except Exception as exc:  # noqa: BLE001 — never crash the daily run on email failure
        log.error("failed to send email: %s", exc)
        return False


def write_preview(html: str, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
