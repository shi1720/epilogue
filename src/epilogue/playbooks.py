"""Institution playbooks — the domain knowledge Epilogue plans with.

Each playbook encodes what really happens when a family notifies one kind of
institution after a death: the steps, the documents that will be demanded,
how long replies take, and where the traps are (benefit overpayments that
must be returned, annual subscriptions that quietly renew, "ghosting" fraud
against a deceased person's credit file).

The Steward reads these when turning the Archivist's account inventory into a
task plan, and the Scribe reads them when drafting correspondence, so a letter
to a bank anticipates the death-certificate request instead of triggering a
two-week round trip to learn it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Playbook(BaseModel):
    id: str
    kinds: list[str] = Field(description="institution kinds this playbook covers")
    category: str
    title: str
    steps: list[str]
    documents_usually_required: list[str] = Field(default_factory=list)
    typical_response_days: int = 7
    risk: str = "routine"  # routine | careful | irreversible
    traps: list[str] = Field(default_factory=list)
    estimated_minutes_saved: int = 45


PLAYBOOKS: dict[str, Playbook] = {
    pb.id: pb
    for pb in [
        Playbook(
            id="bank_notification",
            kinds=["bank", "credit_union"],
            category="financial",
            title="Notify bank and secure accounts",
            steps=[
                "Send written notice of death with the account holder's name and masked account number",
                "Provide certified death certificate when requested",
                "Ask for accounts to be frozen against new charges but keep autopay for the household utilities until transferred",
                "Request date-of-death balance letter (the executor needs it for the estate inventory)",
                "Confirm no safe-deposit box exists, or arrange inventory if one does",
            ],
            documents_usually_required=[
                "certified death certificate",
                "letters testamentary or small-estate affidavit",
            ],
            typical_response_days=7,
            risk="careful",
            traps=[
                "Joint accounts must NOT be closed — the co-owner keeps them; only remove the deceased's name",
                "Autopay for the household (electricity, insurance) dies with the account — transfer it first",
            ],
            estimated_minutes_saved=150,
        ),
        Playbook(
            id="credit_card_closure",
            kinds=["credit_card"],
            category="financial",
            title="Close credit card and stop interest",
            steps=[
                "Notify issuer of death and request account closure with interest frozen as of date of death",
                "Request final statement for the estate",
                "Confirm recurring charges list so subscriptions billed there can be chased individually",
            ],
            documents_usually_required=["death certificate copy"],
            typical_response_days=5,
            risk="careful",
            traps=[
                "Authorized users must stop using the card immediately — charges after death complicate the estate"
            ],
            estimated_minutes_saved=60,
        ),
        Playbook(
            id="ssa_notification",
            kinds=["government"],
            category="government",
            title="Social Security: report death, stop benefits, claim survivor benefits",
            steps=[
                "Confirm the funeral home reported the death to SSA (they usually do); if not, report it",
                "Check whether a benefit payment was made for the month of death — it must be returned",
                "File for the $255 lump-sum death payment for an eligible spouse or child",
                "Screen the survivor for monthly survivor benefits eligibility",
            ],
            documents_usually_required=["death certificate", "deceased's SSN", "survivor's ID"],
            typical_response_days=14,
            risk="careful",
            traps=[
                "Benefits paid for the month of death or later are overpayments and WILL be clawed back — do not spend them",
            ],
            estimated_minutes_saved=180,
        ),
        Playbook(
            id="subscription_cancel",
            kinds=["subscription", "digital", "telecom", "gym"],
            category="subscriptions",
            title="Cancel or transfer a recurring service",
            steps=[
                "Identify billing cadence and next renewal date",
                "Cancel effective immediately, or transfer to a family member where the service supports it",
                "For annual plans, request a prorated refund to the estate",
                "Confirm cancellation in writing",
            ],
            typical_response_days=3,
            risk="routine",
            traps=[
                "Gyms and some carriers demand written notice or even notarized proof — a phone call is not enough",
                "Digital accounts may hold irreplaceable photos or messages — never delete, only stop billing, until the family decides",
            ],
            estimated_minutes_saved=35,
        ),
        Playbook(
            id="utility_transfer",
            kinds=["utility"],
            category="utilities",
            title="Transfer or close household utilities",
            steps=[
                "Decide with the family: keep service on (house occupied or being sold) or close the account",
                "Transfer the account to the estate or surviving resident to avoid service interruption",
                "Settle the final bill from the estate",
            ],
            typical_response_days=5,
            risk="careful",
            traps=[
                "Shutting off power to an empty house in winter can burst pipes — confirm the plan for the property first"
            ],
            estimated_minutes_saved=40,
        ),
        Playbook(
            id="life_insurance_claim",
            kinds=["insurance"],
            category="insurance",
            title="File life insurance claim",
            steps=[
                "Locate the policy number and confirm beneficiaries",
                "Request claim forms from the insurer",
                "Submit certified death certificate with the claim",
                "Track the claim until payout; insurers owe interest on slow payouts in most states",
            ],
            documents_usually_required=["certified death certificate", "policy number", "beneficiary ID"],
            typical_response_days=10,
            risk="careful",
            estimated_minutes_saved=120,
        ),
        Playbook(
            id="credit_bureau_alert",
            kinds=["credit_bureau"],
            category="identity",
            title="Place deceased alert with credit bureaus",
            steps=[
                "Send deceased-do-not-issue-credit alert to Equifax, Experian, and TransUnion",
                "Request a copy of the credit report to catch unknown accounts",
                "Monitor for new inquiries — identity thieves target the recently deceased ('ghosting')",
            ],
            documents_usually_required=["death certificate copy", "proof of authority"],
            typical_response_days=7,
            risk="careful",
            traps=[
                "Nearly 800,000 deceased Americans have their identities misused every year; the window between death and the alert is when it happens",
            ],
            estimated_minutes_saved=90,
        ),
        Playbook(
            id="benefits_scan",
            kinds=["benefits"],
            category="benefits",
            title="Find money the family is owed",
            steps=[
                "Screen for unclaimed property in the state's database under the deceased's names and addresses",
                "Check for employer benefits: final paycheck, unused PTO payout, employer life insurance, 401(k)",
                "Check veteran status for burial allowance and survivor pension",
                "Check refunds owed: prepaid subscriptions, insurance premiums, utility deposits",
            ],
            typical_response_days=14,
            risk="routine",
            estimated_minutes_saved=200,
        ),
        Playbook(
            id="digital_legacy",
            kinds=["digital"],
            category="digital_legacy",
            title="Preserve or memorialize digital accounts",
            steps=[
                "Inventory digital accounts holding memories: photos, email, social profiles",
                "Ask the family what they want preserved before touching anything",
                "Request memorialization (not deletion) where platforms support it",
                "Export archives where the platform allows a legacy download",
            ],
            risk="irreversible",
            typical_response_days=10,
            traps=[
                "Deletion is forever. Photos, voicemails, and messages cannot be recovered. Always ask first."
            ],
            estimated_minutes_saved=80,
        ),
        Playbook(
            id="airline_miles",
            kinds=["airline"],
            category="subscriptions",
            title="Recover loyalty balances",
            steps=[
                "Check the program's bereavement policy — several airlines transfer miles to family on request",
                "Submit transfer request with death certificate before the account is auto-closed for inactivity",
            ],
            typical_response_days=10,
            risk="routine",
            estimated_minutes_saved=45,
        ),
    ]
}


def playbook_for_kind(kind: str) -> Playbook | None:
    for pb in PLAYBOOKS.values():
        if kind in pb.kinds:
            return pb
    return None


def render_playbook(pb: Playbook) -> str:
    lines = [f"PLAYBOOK {pb.id} — {pb.title} (risk: {pb.risk})", "Steps:"]
    lines += [f"  {i + 1}. {s}" for i, s in enumerate(pb.steps)]
    if pb.documents_usually_required:
        lines.append("Documents usually required: " + "; ".join(pb.documents_usually_required))
    lines.append(f"Typical response time: ~{pb.typical_response_days} days")
    if pb.traps:
        lines.append("Traps to avoid:")
        lines += [f"  ! {t}" for t in pb.traps]
    return "\n".join(lines)
