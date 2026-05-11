"""
Prompt loader — reads markdown templates and renders them with Jinja2.

Format:
  prompts/<name>.md is a Jinja2 template. Variables use `{{ var }}` syntax
  (with or without spaces — both work). Control structures (`{% if %}`,
  `{% for %}`) are available if a prompt needs them.

Why Jinja2 (over str.format()):
  - `{{ var }}` is the universal convention across LangChain, LiteLLM,
    Anthropic console, and most LLM prompting docs
  - StrictUndefined raises a clear error when a placeholder lacks a value
    (instead of silently emitting the literal text)
  - Control structures handy for v4 agent prompts that may want to loop
    over the evidence argument list

Loader functions:
  - load_prompt(name, /, *, prompts_dir=None, **variables) -> str
  - list_prompts(prompts_dir=None) -> list[str]
  - required_variables(name, /, *, prompts_dir=None) -> set[str]

The `name` parameter is positional-only (`/`) so `**variables` can include
any key (including `name` or `prompts_dir`) without collision.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta
from jinja2.exceptions import UndefinedError

from config import PROMPTS_DIR


def _build_env(prompts_dir: Path) -> Environment:
    """Construct a Jinja2 Environment rooted at the given directory."""
    return Environment(
        loader=FileSystemLoader(str(prompts_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,         # producing plain-text LLM prompts, not HTML
        trim_blocks=True,         # strip newline immediately after a {% %} tag
        lstrip_blocks=True,       # strip leading whitespace on lines that start with {% %}
    )


def load_prompt(
    name: str,
    /,
    *,
    prompts_dir: Path | None = None,
    **variables: object,
) -> str:
    """
    Load `prompts/<name>.md` and render it with the given variables.

    Args:
        name: The template name without the `.md` extension.
        prompts_dir: Override location of the prompts directory. Defaults to
                     `config.PROMPTS_DIR` (= `<project_root>/prompts/`).
        **variables: Substitution variables. Every `{{ var }}` placeholder
                     in the template must have a matching kwarg.

    Returns:
        The rendered prompt as a string.

    Raises:
        FileNotFoundError: if the template doesn't exist.
        KeyError: if a placeholder lacks a matching kwarg.
    """
    base = prompts_dir if prompts_dir is not None else PROMPTS_DIR
    path = base / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt not found: '{name}' at {path}")

    env = _build_env(base)
    template = env.get_template(f"{name}.md")
    try:
        return template.render(**variables)
    except UndefinedError as e:
        raise KeyError(
            f"Prompt '{name}' has a placeholder without a matching variable: {e}"
        ) from e


def list_prompts(prompts_dir: Path | None = None) -> list[str]:
    """List available prompt template names (without the `.md` extension)."""
    base = prompts_dir if prompts_dir is not None else PROMPTS_DIR
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.md"))


def required_variables(
    name: str,
    /,
    *,
    prompts_dir: Path | None = None,
) -> set[str]:
    """
    Return the set of placeholder names a prompt requires.

    Useful for v4 agents to validate they have everything before calling
    `load_prompt`, rather than discovering it via a KeyError mid-pipeline.
    """
    base = prompts_dir if prompts_dir is not None else PROMPTS_DIR
    path = base / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt not found: '{name}' at {path}")

    env = _build_env(base)
    source = path.read_text(encoding="utf-8")
    ast = env.parse(source)
    return meta.find_undeclared_variables(ast)
