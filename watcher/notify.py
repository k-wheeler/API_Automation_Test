"""Build and send the email digest via Gmail SMTP.

Requires the GMAIL_APP_PASSWORD environment variable (a Google App Password, not
the account password). No email is sent when there are no matches.
"""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.message import EmailMessage

GMAIL_ADDRESS = "kwheelerecology@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def build_html(matches: list[dict]) -> str:
    """matches: list of {company, title, location, url, reasons}."""
    rows = []
    for m in matches:
        loc = f" — {html.escape(m['location'])}" if m.get("location") else ""
        reasons = ", ".join(html.escape(r) for r in m.get("reasons", []))
        rows.append(
            f"""
            <li style="margin-bottom:14px;">
              <a href="{html.escape(m['url'])}" style="font-weight:600;font-size:15px;">
                {html.escape(m['title'])}</a><br>
              <span style="color:#555;">{html.escape(m['company'])}{loc}</span><br>
              <span style="color:#888;font-size:12px;">matched: {reasons}</span>
            </li>"""
        )
    return f"""\
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
  <h2 style="margin-bottom:4px;">New relevant job postings</h2>
  <p style="color:#666;margin-top:0;">{len(matches)} match(es)</p>
  <ul style="list-style:none;padding-left:0;">{''.join(rows)}</ul>
  <p style="color:#aaa;font-size:11px;">Sent by job-watcher.</p>
</body></html>"""


def build_text(matches: list[dict]) -> str:
    lines = [f"New relevant job postings ({len(matches)}):", ""]
    for m in matches:
        loc = f" — {m['location']}" if m.get("location") else ""
        lines.append(f"* {m['title']} — {m['company']}{loc}")
        lines.append(f"  {m['url']}")
        if m.get("reasons"):
            lines.append(f"  matched: {', '.join(m['reasons'])}")
        lines.append("")
    return "\n".join(lines)


def send_digest(matches: list[dict], *, dry_run: bool = False) -> None:
    if not matches:
        print("No new relevant postings — no email sent.")
        return

    subject = f"[job-watcher] {len(matches)} new relevant posting(s)"
    text_body = build_text(matches)
    html_body = build_html(matches)

    if dry_run:
        print("--- DRY RUN: would send this email ---")
        print(f"Subject: {subject}\n")
        print(text_body)
        return

    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        raise RuntimeError(
            "GMAIL_APP_PASSWORD is not set. Add it as a GitHub Actions secret "
            "(or export it locally) — it's a Google App Password."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(GMAIL_ADDRESS, password)
        server.send_message(msg)
    print(f"Sent digest with {len(matches)} posting(s) to {GMAIL_ADDRESS}.")
