from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class FilterRules:
    sender_whitelist: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    poll_interval_seconds: int = 300
    max_summary_tokens: int = 400


def load_config(rules_path: str = "rules.json") -> FilterRules:
    rules_file = Path(rules_path)
    if not rules_file.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_path}")

    with open(rules_file) as f:
        data = json.load(f)

    return FilterRules(
        sender_whitelist=data.get("sender_whitelist", []),
        keywords=data.get("keywords", []),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", 300)),
        max_summary_tokens=int(os.getenv("MAX_SUMMARY_TOKENS", 400)),
    )


if __name__ == "__main__":
    config = load_config()
    print("Loaded FilterRules:")
    print(f"  sender_whitelist : {config.sender_whitelist}")
    print(f"  keywords         : {config.keywords}")
    print(f"  poll_interval    : {config.poll_interval_seconds}s")
    print(f"  max_summary_tokens: {config.max_summary_tokens}")
