"""Shared runtime context for one Epilogue case, plus the Decision Gate.

The Decision Gate is the load-bearing safety mechanism of the product. The
Steward's system prompt asks it to be careful; the gate *makes* it careful.
Every outward action passes through :func:`gate_check` in plain code, so even
a confused model cannot take an irreversible or expensive action without a
resolved human decision on file. Defense in depth: the prompt persuades, the
gate enforces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .domain import AutonomyLevel, Case, TaskItem
from .ledger import Ledger
from .simworld import SimWorld

# Documents the family placed in Epilogue's vault at intake. Certified death
# certificate copies are a real, finite resource — families are told to order
# ten and still run out — so the vault counts them.
DEFAULT_VAULT = {
    "certified_death_certificate": 5,
    "death_certificate_copy": -1,  # -1 = unlimited photocopies
    "letters_testamentary": 3,
    "executor_id_copy": -1,
}


def vault_status(ledger: Ledger, case_id: str) -> dict[str, int]:
    """Current document counts for a case (shared by the Runtime and the dashboard)."""
    out = {}
    for doc, initial in DEFAULT_VAULT.items():
        raw = ledger.kv_get(f"vault:{case_id}:{doc}")
        out[doc] = int(raw) if raw is not None else initial
    return out


@dataclass
class GateResult:
    allowed: bool
    reason: str


@dataclass
class Runtime:
    ledger: Ledger
    world: SimWorld
    case: Case
    extra: dict = field(default_factory=dict)

    # -- document vault ----------------------------------------------------

    def _vault_key(self, doc: str) -> str:
        return f"vault:{self.case.id}:{doc}"

    def vault_status(self) -> dict[str, int]:
        return vault_status(self.ledger, self.case.id)

    def vault_take(self, doc: str) -> bool:
        """Consume one copy of a document. Returns False if none remain."""
        status = self.vault_status()
        if doc not in status:
            return False
        remaining = status[doc]
        if remaining == -1:
            return True
        if remaining <= 0:
            return False
        self.ledger.kv_set(self._vault_key(doc), str(remaining - 1))
        return True

    # -- decision gate -----------------------------------------------------

    def gate_check(self, task: TaskItem, action_summary: str, moves_money_usd: float = 0.0) -> GateResult:
        contract = self.case.contract
        level = contract.level_for(task.category)
        approved = self.ledger.resolved_decision_for_task(task.id)

        def blocked(why: str) -> GateResult:
            return GateResult(
                allowed=False,
                reason=(
                    f"BLOCKED BY DECISION GATE: {why} "
                    f"No approved decision is on file for this matter. Use the ask_survivor tool to "
                    f"surface a clear decision (with options and your recommendation), then wait. Do "
                    f"NOT retry this action until the survivor has answered."
                ),
            )

        # Money is checked first, and a category approval is never enough: a move above
        # the threshold requires a resolved decision that EXPLICITLY authorizes at least
        # that amount (ask_survivor's authorizes_amount_usd). This keeps one approved
        # question ("transfer the profiles?") from silently authorizing later transfers.
        if moves_money_usd and moves_money_usd > contract.financial_threshold_usd:
            authorized = approved is not None and (approved.authorizes_amount_usd or 0.0) >= moves_money_usd
            if not authorized:
                return blocked(
                    f"This action moves or forfeits ${moves_money_usd:,.2f}, above the survivor's "
                    f"${contract.financial_threshold_usd:,.2f} threshold, and no resolved decision "
                    f"explicitly authorizes that amount (set authorizes_amount_usd when asking)."
                )
        if approved is not None:
            return GateResult(True, f"Survivor decision {approved.id} on file — action authorized.")
        if task.risk == "irreversible" or level == AutonomyLevel.ASK_FIRST:
            return blocked(
                f"'{task.title}' is in category '{task.category}' (autonomy: ask_first / risk: {task.risk})."
            )
        return GateResult(True, f"Within autonomy contract ({level.value}).")

    # -- convenience -------------------------------------------------------

    def case_brief(self) -> str:
        c = self.case
        stats = self.ledger.stats(c.id)
        contract_lines = [f"  - {cat}: {lvl.value}" for cat, lvl in c.contract.defaults.items()]
        vault_lines = [
            f"  - {doc}: {'unlimited' if n == -1 else n + 0}" for doc, n in self.vault_status().items()
        ]
        return "\n".join(
            [
                f"CASE {c.id} — settling the affairs of {c.deceased.full_name} "
                f"({c.deceased.date_of_birth} – {c.deceased.date_of_death})",
                f"Survivor: {c.survivor.full_name} ({c.survivor.relationship}"
                + (", executor)" if c.survivor.is_executor else ")"),
                f"Simulated date today: {stats['sim_today']}",
                f"Matters: {stats['total_matters']} total, {stats['settled']} settled, "
                f"{stats['in_motion']} in motion, {stats['waiting_on_you']} awaiting the survivor",
                "Autonomy contract (what the survivor allows without asking):",
                *contract_lines,
                f"Hard rule: any single action moving more than ${c.contract.financial_threshold_usd:,.0f} asks first.",
                "Document vault:",
                *vault_lines,
                f"The survivor said at intake: {json.dumps(c.narrative[:600])}",
            ]
        )
