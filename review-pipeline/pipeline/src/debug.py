# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tiny debug-logging facility.

A single on/off flag controls whether `debug_print` emits anything. The flag
is sourced from `config.json` in the input bucket (key: "debug", default on)
and set once per run via `set_debug`. When on, messages print to stdout, which
in Lambda means they land in CloudWatch.
"""

from __future__ import annotations

from typing import Any

# Default ON, per requirement. Overridden per run from config.json.
_DEBUG: bool = True


def set_debug(enabled: bool) -> None:
    """Set the global debug flag for this run."""
    global _DEBUG
    _DEBUG = bool(enabled)


def debug_enabled() -> bool:
    return _DEBUG


def debug_print(*args: Any) -> None:
    """Print only when debug is on; otherwise do nothing."""
    if _DEBUG:
        print("[DEBUG]", *args)
