"""simworld: institution behaviors, delivery queue, ambient events."""

from epilogue.simworld import SimWorld


def _submit(world, case, task_id, inst, channel="secure_message", body="notice of death", attachments=None):
    return world.submit(case.id, task_id, inst, channel, "Notice of death", body, attachments or [])


def test_bank_demands_certified_documents_then_settles(ledger, case):
    world = SimWorld(ledger)
    receipt = _submit(world, case, "t1", "first_harbor_bank")
    assert "First Harbor Bank" in receipt
    # No mail yet — the reply is scheduled days out.
    assert ledger.unread_mail(case.id) == []
    ledger.advance_days(3)
    delivered = world.deliver_due(case.id)
    assert len(delivered) == 1
    assert "certified" in delivered[0].body.lower()
    # Second round with the certificate attached settles the matter.
    _submit(world, case, "t1", "first_harbor_bank", attachments=["certified_death_certificate"])
    ledger.advance_days(4)
    delivered = world.deliver_due(case.id)
    assert "date-of-death balance" in delivered[0].subject.lower()
    assert world.get_stage("first_harbor_bank", "t1") == "done"


def test_gym_swallows_portal_requests_but_honors_letters(ledger, case):
    world = SimWorld(ledger)
    receipt = _submit(world, case, "t2", "ironworks_gym", channel="portal_form")
    assert "no confirmation" in receipt
    ledger.advance_days(10)
    assert world.deliver_due(case.id) == []  # silence — the follow-up loop must catch this
    # A second portal attempt gets told the truth; a letter finally works.
    _submit(world, case, "t2", "ironworks_gym", channel="portal_form")
    ledger.advance_days(2)
    told = world.deliver_due(case.id)
    assert told and "WRITTEN NOTICE" in told[0].body
    _submit(world, case, "t2", "ironworks_gym", channel="letter")
    ledger.advance_days(3)
    done = world.deliver_due(case.id)
    assert done and "refund" in done[0].body.lower()


def test_fraud_attempt_succeeds_when_no_alert_was_placed(ledger, case):
    """The thief strikes on day 9 either way; with no deceased alert on file, the
    application goes through — the world genuinely depends on the agent's work."""
    world = SimWorld(ledger)
    world.seed_case_events(case.id)
    assert world.deliver_due(case.id) == []
    ledger.advance_days(9)
    delivered = world.deliver_due(case.id)
    subjects = " | ".join(m.subject for m in delivered)
    assert "new account opened" in subjects.lower()


def test_fraud_attempt_blocked_by_deceased_alert(ledger, case):
    world = SimWorld(ledger)
    world.seed_case_events(case.id)
    # The agent places a deceased alert before day 9.
    _submit(world, case, "t9", "experian_sim")
    ledger.advance_days(3)
    world.deliver_due(case.id)  # bureau confirms; stage -> done
    ledger.advance_days(6)
    delivered = world.deliver_due(case.id)
    subjects = " | ".join(m.subject for m in delivered)
    assert "blocked" in subjects.lower()


def test_renewal_reminder_suppressed_once_settled(ledger, case):
    world = SimWorld(ledger)
    world.seed_case_events(case.id)
    # Settle PixelVault before the reminder is due.
    _submit(world, case, "t3", "pixelvault", body="please export the archive")
    world.set_stage("pixelvault", "t3", "done")
    ledger.advance_days(8)
    delivered = world.deliver_due(case.id)
    assert all("renews" not in m.subject for m in delivered)


def test_unknown_institution_is_reported_not_raised(ledger, case):
    world = SimWorld(ledger)
    out = _submit(world, case, "t4", "bank_of_narnia")
    assert out.startswith("ERROR: unknown institution")


def test_bank_rejects_photocopies_certified_only(ledger, case):
    """'Photocopies are not accepted' is enforced, so the finite certified
    copies in the vault are a real constraint, not a UI ornament."""
    world = SimWorld(ledger)
    _submit(world, case, "t8", "first_harbor_bank", attachments=["death_certificate_copy"])
    ledger.advance_days(3)
    delivered = world.deliver_due(case.id)
    assert delivered and "Photocopies are not accepted" in delivered[0].subject
    assert world.get_stage("first_harbor_bank", "t8") != "done"
    _submit(world, case, "t8", "first_harbor_bank", attachments=["certified_death_certificate"])
    ledger.advance_days(4)
    delivered = world.deliver_due(case.id)
    assert delivered and "date-of-death balance" in delivered[0].subject.lower()
