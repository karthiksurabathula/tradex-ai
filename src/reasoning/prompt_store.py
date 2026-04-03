"""Versioned prompt management — stores and retrieves prompt versions for the feedback loop."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from src.reasoning.senior_trader import SENIOR_TRADER_SYSTEM_PROMPT


class PromptStore:
    """Manages versioned Senior Trader prompts on disk."""

    def __init__(self, prompt_dir: str = "data/prompt_versions"):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        self._current_prompt = SENIOR_TRADER_SYSTEM_PROMPT

    @property
    def current(self) -> str:
        return self._current_prompt

    @current.setter
    def current(self, prompt: str):
        self._current_prompt = prompt

    def save_version(self, prompt: str, trigger_context: dict | None = None) -> str:
        """Save a new prompt version to disk. Returns the version ID."""
        version = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        path = self.prompt_dir / f"v_{version}.json"
        path.write_text(
            json.dumps(
                {
                    "version": version,
                    "prompt": prompt,
                    "trigger_context": trigger_context or {},
                    "saved_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
                default=str,
            )
        )
        self._current_prompt = prompt
        return version

    def load_version(self, version: str) -> str:
        """Load a specific prompt version from disk."""
        path = self.prompt_dir / f"v_{version}.json"
        data = json.loads(path.read_text())
        return data["prompt"]

    def list_versions(self) -> list[str]:
        """List all saved prompt versions, newest first."""
        files = sorted(self.prompt_dir.glob("v_*.json"), reverse=True)
        return [f.stem.replace("v_", "") for f in files]

    def latest_version(self) -> str | None:
        """Get the most recent saved version ID, or None if no versions exist."""
        versions = self.list_versions()
        return versions[0] if versions else None
