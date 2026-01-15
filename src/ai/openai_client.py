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

        # Responses API: create response from input text/messages. :contentReference[oaicite:1]{index=1}
        resp = self.client.responses.create(
            prompt={
                "id": "pmpt_696951ae22848197b60602b18f7691ed0610c009176ab218",
                "version": "1"
            },
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "{\n{\nlast_move: A\n}\n}" # memory buffer
                        },
                        {
                            "type": "input_image",
                            "image_url": "data:image/jpeg;base64,..."
                        }
                    ]
                },
            ],
            reasoning={
                "summary": "auto"
            },
            store=True,
            include=[
                "reasoning.encrypted_content",
                "web_search_call.action.sources"
            ]
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
