#!/usr/bin/env python3
"""ci/artifacts.py - JSON artifact repository (rules 4/6/19).

All inter-stage state flows through here, never through stdout scraping or env vars.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class ArtifactRepository:
    """Read/write ci/artifacts/*.json through a single entry point."""

    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self._root / name

    def load(self, name: str) -> dict[str, Any]:
        p = self.path(name)
        if not p.exists():
            log.debug("artifact not found: %s (empty dict)", p)
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        log.debug("loaded %s (%d keys)", name, len(data))
        return data

    def save(self, name: str, data: dict[str, Any]) -> None:
        p = self.path(name)
        p.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("artifact wrote %s", p)

    def update(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Read-modify-write: load -> update fields -> save."""
        data = self.load(name)
        data.update(kwargs)
        self.save(name, data)
        return data
