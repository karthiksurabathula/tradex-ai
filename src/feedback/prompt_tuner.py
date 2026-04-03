"""LLM-driven prompt refinement based on trade performance analysis."""

from __future__ import annotations

import json
import logging

from anthropic import Anthropic

from src.reasoning.prompt_store import PromptStore

logger = logging.getLogger(__name__)


class PromptTuner:
    """Uses an LLM to suggest targeted prompt refinements based on trade outcomes."""

    def __init__(self, prompt_store: PromptStore, model: str = "claude-sonnet-4-6"):
        self.prompt_store = prompt_store
        self.model = model
        self.client = Anthropic()

    def refine(self, review_result: dict) -> str:
        """Ask an LLM to suggest prompt refinements based on trade performance.

        Returns the refined prompt and saves it as a new version.
        """
        current_prompt = self.prompt_store.current

        logger.info("Requesting prompt refinement from %s", self.model)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": f"""You are a trading system optimizer. Given the current Senior Trader
prompt and recent performance data, suggest specific prompt modifications
to improve decision quality.

CURRENT PROMPT:
{current_prompt}

PERFORMANCE DATA:
{json.dumps(review_result, indent=2, default=str)}

Rules:
- Only suggest SMALL, targeted changes (1-2 sentences max)
- Focus on the weakest area (highest loss pattern frequency)
- Never remove risk management guardrails
- Preserve the structured output format (SIGNAL/CONFIDENCE/QUANTITY/REASONING)
- If performance is acceptable (win rate > 50%, profit factor > 1.5), make NO changes
  and return the prompt unchanged
- Output ONLY the full revised prompt text, nothing else
""",
                }
            ],
        )
        refined = response.content[0].text.strip()

        # Save versioned prompt
        version = self.prompt_store.save_version(refined, review_result)
        logger.info("Saved refined prompt version: %s", version)

        return refined
