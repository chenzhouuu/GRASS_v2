"""Message-history trimming that preserves tool-call/tool-response pairing."""

from typing import List

from langchain_core.messages import BaseMessage, ToolMessage


def trim_history(history: List[BaseMessage], max_messages: int) -> List[BaseMessage]:
    """Keep the first message plus (at most) the last ``max_messages``.

    The kept window never starts on a ToolMessage: when the cut lands between
    an assistant tool-call message and its tool responses, the orphaned
    ToolMessages are dropped from the front of the window, because
    OpenAI-compatible APIs reject a tool response with no preceding tool-call
    message (hard 400). Pairs fully inside the window are unaffected — only
    the window's leading edge can split a pair.
    """
    if len(history) <= max_messages:
        return list(history)
    window = history[-max_messages:]
    start = 0
    while start < len(window) and isinstance(window[start], ToolMessage):
        start += 1
    return [history[0]] + window[start:]
