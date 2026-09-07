"""AgentLab model adapter for Qwen models served through an OpenAI-compatible API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial

import litellm
from agentlab.llm.litellm_api import LiteLLMModel, LiteLLMModelArgs, completion
from agentlab.llm.response_api import BaseModelWithPricing


class QwenLiteLLMModel(LiteLLMModel):
    """Keep unknown LiteLLM pricing from discarding an otherwise valid response."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = 100,
        use_only_first_toolcall: bool = False,
    ) -> None:
        # AgentLab logs missing LiteLLM metadata as ERROR twice during the stock
        # constructor. Initialize the same client without treating optional pricing
        # metadata as an execution failure.
        BaseModelWithPricing.__init__(
            self,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.action_space_as_tools = True
        client_args = {}
        if base_url is not None:
            client_args["base_url"] = base_url
        if api_key is not None:
            client_args["api_key"] = api_key
        self.client = partial(completion, **client_args)
        self.use_only_first_toolcall = use_only_first_toolcall
        self._pricing_api = "litellm"
        try:
            self.litellm_info = litellm.get_model_info(model_name)
            self.input_cost = float(self.litellm_info.get("input_cost_per_token", 0.0))
            self.output_cost = float(self.litellm_info.get("output_cost_per_token", 0.0))
            self.pricing_available = True
        except Exception:
            self.litellm_info = {}
            self.input_cost = 0.0
            self.output_cost = 0.0
            self.pricing_available = False
            logging.warning("No LiteLLM price for %s; effective_cost=0", model_name)
        self.reset_stats()

    def get_effective_cost(self, response) -> float:
        if not self.pricing_available:
            return 0.0
        return super().get_effective_cost(response)


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
