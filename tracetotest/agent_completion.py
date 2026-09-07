"""Agent-controlled completion protocol for open-ended BrowserGym runs."""

from __future__ import annotations

from typing import Sequence

from browsergym.core.action.highlevel import HighLevelActionSet


COMPLETION_MESSAGE_PREFIX = "TRACE2TEST_TASK_COMPLETE: "
COMPLETION_ACTION_VERSION = "1.0.0"


def finish_task(reason: str):
    """Declare that the current browser state satisfies the task and end the Agent episode.

    Call this immediately after verifying that the goal is complete. Do not call it
    speculatively. A separate post-run verifier, not this declaration, decides whether
    the task actually passed.

    Examples:
        finish_task("The requested page is open and its URL and heading match the goal.")
    """
    send_message_to_user("TRACE2TEST_TASK_COMPLETE: " + reason)


class AgentCompletionActionSet(HighLevelActionSet):
    """BrowserGym bid actions plus Trace2Test's explicit completion action."""

    def __init__(self, subsets: Sequence[str] = ("bid",), *, multiaction: bool = False):
        self._base_action_set = HighLevelActionSet(
            subsets=list(subsets), multiaction=multiaction
        )
        super().__init__(
            subsets=[*subsets, "custom"],
            custom_actions=[finish_task],
            multiaction=multiaction,
        )

    def to_tool_description(self, api="openai", add_examples=True) -> list[dict]:
        """Describe built-ins normally and append the custom completion tool."""
        tools = self._base_action_set.to_tool_description(
            api=api, add_examples=add_examples
        )
        schema_key = "input_schema" if api == "anthropic" else "parameters"
        description = self.action_set["finish_task"].description
        examples = self.action_set["finish_task"].examples
        if add_examples and examples:
            description += "\n\nExamples:\n" + "".join(
                f"- {example}\n" for example in examples
            )
        tool = {
            "name": "finish_task",
            "description": description,
            schema_key: {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        }
        if api == "openai":
            tool["type"] = "function"
        tools.append(tool)
        return tools


def completion_reason(chat_messages: list[dict]) -> str | None:
    """Return the latest reason declared by the Agent, if present."""
    for message in reversed(chat_messages):
        text = str(message.get("message") or "")
        if message.get("role") == "assistant" and text.startswith(COMPLETION_MESSAGE_PREFIX):
            return text.removeprefix(COMPLETION_MESSAGE_PREFIX).strip()
    return None
