"""Verifiers: pure functions from artifact to verdict, and their composition."""

from decidable.verifiers.base import (
    StackResult,
    Verifier,
    VerifierStack,
    error_verdict,
)

__all__ = ["StackResult", "Verifier", "VerifierStack", "error_verdict"]
