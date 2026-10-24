"""Proctor — the exam proctor for AI coding agents.

Catches agents that game their own evaluation (skipped tests, weakened
assertions, rigged harnesses, answer-key special-casing) and measures whether
their work generalizes to tests they never saw.
"""

__version__ = "0.2.0"
