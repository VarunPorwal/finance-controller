"""The deterministic half of the instruction layer — PRD §8.3, §8.5, §9.2.

A model turns a sentence into a command shape. Everything after that is here,
and none of it is a model: params present, references resolve, amounts agree,
permission held, nothing moved underneath us. Then the effects are derived and
a preview is rendered for a human to confirm.

This package imports no LLM and needs no database, which is the point. The
component that checks the model's output cannot itself depend on the model, and
the seven push-back rules in §8.5 are unit-testable without either.
"""

from __future__ import annotations
