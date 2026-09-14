"""simworld — a small simulated outside world for Epilogue.

Real estate settlement means writing to banks, agencies, and subscription
services and waiting days for imperfect answers. simworld reproduces that
texture faithfully — document demands, silent non-replies, clawback notices,
fraud attempts against the deceased's identity — so the whole agent pipeline
can be exercised end-to-end, deterministically, without touching a real
institution.

In production these adapters are swapped for real channels (secure email,
institution portals, print-and-mail APIs, and partner integrations), which is
exactly how commercial services in this space operate today. The agent code
above this layer does not change.
"""

from .world import INSTITUTIONS, Institution, SimWorld

__all__ = ["SimWorld", "INSTITUTIONS", "Institution"]
