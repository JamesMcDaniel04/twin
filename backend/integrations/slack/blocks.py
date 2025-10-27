"""Slack Block Kit builders."""

from __future__ import annotations


def build_summary_block(title: str, body: str):
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*{title}*\n{body}"},
    }
