from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from dotenv import load_dotenv

from openai import OpenAI

load_dotenv()  # Load environment variables from .env file


@dataclass(frozen=True)
class AIConfig:
    model: str = "gpt-5.2"
    temperature: float = 0.2


class OpenAIBrain:
    def __init__(self, cfg: AIConfig):
        self.cfg = cfg
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def decide_next_input(self, *, state_summary: str) -> Dict[str, Any]:
        """
        Returns a dict decision (you can validate it with pydantic/dataclasses).
        Uses JSON-only output so parsing stays robust.
        """
        instructions = (
            "You are playing Pokémon Emerald. "
            "Return ONLY valid JSON with keys: "
            "{button: string, reason: string, confidence: number}.\n"
            "button must be one of: A,B,START,SELECT,UP,DOWN,LEFT,RIGHT,L,R,NONE."
        )

        # Responses API: create response from input text/messages. :contentReference[oaicite:1]{index=1}
        resp = self.client.responses.create(
            model=self.cfg.model,
            instructions=instructions,
            input=state_summary,
            temperature=self.cfg.temperature,
        )

        # The SDK exposes aggregated text via output_text in docs. :contentReference[oaicite:2]{index=2}
        text = getattr(resp, "output_text", None) or ""
        text = text.strip()

        # Be defensive: model should return JSON, but don’t trust it blindly.
        try:
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("AI output was not a JSON object")
            return obj
        except Exception:
            return {
                "button": "NONE",
                "reason": f"Non-JSON or unparsable AI output: {text[:200]}",
                "confidence": 0.0,
            }
