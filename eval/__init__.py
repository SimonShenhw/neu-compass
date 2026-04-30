"""Evaluation harness — Ragas runners, prompt comparators, eval set generators.

Note: this directory is intentionally NOT in pyproject.toml's wheel package
list (would shadow Python's builtin eval()). Modules here are importable
via `from eval.compare_prompts import ...` because pytest pythonpath = ['.']
adds the project root.
"""
