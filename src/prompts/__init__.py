"""Prompt template loader — markdown files in `prompts/` with {var} placeholders."""

from prompts.loader import load_prompt, list_prompts

__all__ = ["load_prompt", "list_prompts"]
