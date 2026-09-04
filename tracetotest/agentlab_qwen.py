"""AgentLab model adapter for Qwen models served through an OpenAI-compatible API."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentlab.llm.litellm_api import LiteLLMModel, LiteLLMModelArgs


class QwenLiteLLMModel(LiteLLMModel):
    """Keep unknown LiteLLM pricing from discarding an otherwise valid response."""

    def get_effective_cost(self, response) -> float:
        try:
            return super().get_effective_cost(response)
        except Exception as error:
            logging.warning("Qwen pricing is unavailable; recording effective_cost=0: %s", error)
            return 0.0


@dataclass
class QwenLiteLLMModelArgs(LiteLLMModelArgs):
    def make_model(self) -> QwenLiteLLMModel:
        return QwenLiteLLMModel(
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            max_tokens=self.max_new_tokens,
            temperature=self.temperature,
            use_only_first_toolcall=self.use_only_first_toolcall,
        )

