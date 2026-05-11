"""Tests for the prompt loader — Jinja2 templates with {{ var }} placeholders."""

import pytest

from prompts.loader import load_prompt, list_prompts, required_variables


def _write(dir_, name: str, content: str) -> None:
    (dir_ / f"{name}.md").write_text(content, encoding="utf-8")


def test_load_prompt_substitutes_variables(tmp_path):
    _write(tmp_path, "greet", "Hello {{ name }}!")
    out = load_prompt("greet", prompts_dir=tmp_path, name="World")
    assert out == "Hello World!"


def test_load_prompt_multiple_vars(tmp_path):
    _write(tmp_path, "summary", "Topic: {{ topic }}\nEvidence: {{ evidence }}")
    out = load_prompt(
        "summary",
        prompts_dir=tmp_path,
        topic="ignition",
        evidence="grinder + aerosol",
    )
    assert "Topic: ignition" in out
    assert "Evidence: grinder + aerosol" in out


def test_load_prompt_works_without_spaces_in_braces(tmp_path):
    """Both `{{ var }}` and `{{var}}` should work — Jinja2 is whitespace-tolerant."""
    _write(tmp_path, "tight", "{{name}} and {{ name }}")
    out = load_prompt("tight", prompts_dir=tmp_path, name="X")
    assert out == "X and X"


def test_load_prompt_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        load_prompt("nonexistent", prompts_dir=tmp_path)


def test_load_prompt_missing_variable(tmp_path):
    _write(tmp_path, "needs_var", "Hello {{ missing_arg }}!")
    with pytest.raises(KeyError, match="missing_arg"):
        load_prompt("needs_var", prompts_dir=tmp_path)


def test_load_prompt_passes_through_single_braces(tmp_path):
    """Single { } are literal in Jinja2 — only {{ }} are variable delimiters."""
    _write(tmp_path, "code", "function f() { return {{ value }}; }")
    out = load_prompt("code", prompts_dir=tmp_path, value="42")
    assert out == "function f() { return 42; }"


def test_load_prompt_supports_jinja_for_loop(tmp_path):
    """Jinja2 control structures should work — useful for iterating evidence."""
    _write(tmp_path, "loop", "{% for x in items %}- {{ x }}\n{% endfor %}")
    out = load_prompt("loop", prompts_dir=tmp_path, items=["a", "b", "c"])
    assert "- a\n" in out
    assert "- b\n" in out
    assert "- c\n" in out


def test_list_prompts(tmp_path):
    _write(tmp_path, "agent_a", "x")
    _write(tmp_path, "agent_b", "y")
    _write(tmp_path, "agent_c", "z")
    assert list_prompts(prompts_dir=tmp_path) == ["agent_a", "agent_b", "agent_c"]


def test_list_prompts_empty_dir(tmp_path):
    assert list_prompts(prompts_dir=tmp_path) == []


def test_list_prompts_missing_dir(tmp_path):
    """Should not raise if the prompts dir doesn't exist."""
    missing = tmp_path / "does_not_exist"
    assert list_prompts(prompts_dir=missing) == []


def test_required_variables(tmp_path):
    _write(tmp_path, "tpl", "Hello {{ name }}, welcome to {{ place }}.")
    assert required_variables("tpl", prompts_dir=tmp_path) == {"name", "place"}


def test_required_variables_no_vars(tmp_path):
    _write(tmp_path, "static", "No placeholders here.")
    assert required_variables("static", prompts_dir=tmp_path) == set()


def test_required_variables_repeated(tmp_path):
    _write(tmp_path, "repeat", "{{ a }} then {{ a }} again, plus {{ b }}")
    assert required_variables("repeat", prompts_dir=tmp_path) == {"a", "b"}


def test_smoke_test_prompt_loads_from_real_dir():
    """The committed prompts/_smoke_test.md should load with the real PROMPTS_DIR."""
    out = load_prompt(
        "_smoke_test",
        topic="ignition",
        evidence="grinder + aerosol",
    )
    assert "Topic: ignition" in out
    assert "Evidence: grinder + aerosol" in out
