from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class FilterRules:
    # name -> subject keywords (Emails pipeline matches on subject)
    thread_list: dict[str, list[str]] = field(default_factory=dict)
    # group name -> sender substrings (Invoices pipeline matches on sender)
    invoice_groups: dict[str, list[str]] = field(default_factory=dict)
    poll_interval_seconds: int = 300
    max_summary_tokens: int = 400


def load_config(rules_path: str = "rules.json") -> FilterRules:
    rules_file = Path(rules_path)
    if not rules_file.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_path}")

    with open(rules_file) as f:
        data = json.load(f)

    return FilterRules(
        thread_list=data.get("thread_list", {}),
        invoice_groups=data.get("invoice_groups", {}),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", 300)),
        max_summary_tokens=int(os.getenv("MAX_SUMMARY_TOKENS", 400)),
    )


if __name__ == "__main__":
    config = load_config()
    print("Loaded FilterRules:")
    print(f"  thread_list      : {config.thread_list}")
    print(f"  invoice_groups   : {config.invoice_groups}")
    print(f"  poll_interval    : {config.poll_interval_seconds}s")
    print(f"  max_summary_tokens: {config.max_summary_tokens}")
