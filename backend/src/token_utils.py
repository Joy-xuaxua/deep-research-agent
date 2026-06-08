"""Token counting and truncation utilities using tiktoken."""

from __future__ import annotations

import tiktoken

_ENCODING = None


def _get_encoding():
    """Get or create a cached tiktoken encoding instance."""
    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return _ENCODING


def count_tokens(text: str) -> int:
    """Count the number of tokens in text using GPT-4 tokenizer.

    Args:
        text: The text to count tokens for

    Returns:
        Number of tokens in the text
    """
    if not text:
        return 0
    return len(_get_encoding().encode(text))


def truncate_to_tokens(
    text: str,
    max_tokens: int,
    suffix: str = "... [truncated]"
) -> str:
    """Truncate text to a maximum number of tokens.

    Uses the GPT-4 tokenizer (cl100k_base) which is reasonably compatible
    with many modern LLMs and handles CJK languages correctly.

    Args:
        text: The text to truncate
        max_tokens: Maximum number of tokens to keep
        suffix: Suffix to append if truncation occurs

    Returns:
        Truncated text with suffix if shortened, or original text if fits
    """
    encoding = _get_encoding()
    tokens = encoding.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return encoding.decode(tokens[:max_tokens]) + suffix
