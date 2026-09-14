"""Validate coverage and safety after the model proposes a matter plan.

The model owns wording and reasoning; established institution kinds determine
risk. A missing account cannot disappear merely because the planner omitted it.
"""
from __future__ import annotations

from .domain import AccountInventory, PlannedTask, TaskPlan
from .playbooks import PLAYBOOKS, playbook_for_kind
from .simworld import INSTITUTIONS

ALIASES = {
    'first_harbor_bank': ('first harbor',), 'meridian_card': ('meridian card',),
    'fed_benefits': ('fed benefit', 'federal benefits', 'social security'),
    'ohio_light_power': ('ohio light',), 'streamflix': ('streamflix',),
    'pixelvault': ('pixelvault',), 'ironworks_gym': ('ironworks',),
    'beacon_mutual': ('beacon mutual',), 'skyway_airlines': ('skyway',),
    'clearline_wireless': ('clearline',), 'daily_ledger_news': ('daily ledger',),
    'equifax_sim': ('equifax',), 'experian_sim': ('experian',), 'transunion_sim': ('transunion',),
}


def match_institution(text):
    text = text.lower()
    return next((key for key, aliases in ALIASES.items() if any(alias in text for alias in aliases)), None)


def complete_plan(plan: TaskPlan, inventory: AccountInventory, documents: str = '') -> TaskPlan:
    required = {}
    for account in inventory.accounts:
        key = match_institution(account.institution_name)
        required[key or account.institution_name] = (key, account.institution_kind, account.evidence)
    # Extract only explicitly named, known simulation institutions from source documents.
    for key, aliases in ALIASES.items():
        evidence = next((line.strip() for line in documents.splitlines() if any(a in line.lower() for a in aliases)), None)
        if evidence:
            required.setdefault(key, (key, INSTITUTIONS[key].kind, evidence))
    for key in ('equifax_sim','experian_sim','transunion_sim'):
        required.setdefault(key, (key,'credit_bureau','Standard deceased-identity protection in the case playbook.'))
    tasks, covered = [], set()
    for task in plan.tasks:
        key = task.institution_id if task.institution_id in INSTITUTIONS else match_institution(task.title)
        if key:
            if key in covered:
                continue
            task.institution_id = key
            pb = playbook_for_kind(INSTITUTIONS[key].kind)
            if pb:
                task.category, task.playbook_id = pb.category, pb.id
                if task.risk != 'irreversible':
                    task.risk = pb.risk
            if INSTITUTIONS[key].kind == 'digital':
                task.category, task.risk = 'digital_legacy', 'irreversible'
            covered.add(key)
        tasks.append(task)
    for name, (key, kind, evidence) in required.items():
        if key and key in covered:
            continue
        if not key and any(name.lower() in task.title.lower() for task in tasks):
            continue
        pb = playbook_for_kind(kind)
        title = INSTITUTIONS[key].name if key else name
        tasks.append(PlannedTask(
            title=f'{pb.title if pb else "Review account"} — {title}',
            institution_id=key, playbook_id=pb.id if pb else None,
            category='digital_legacy' if kind == 'digital' else pb.category if pb else 'financial',
            risk='irreversible' if kind == 'digital' else pb.risk if pb else 'careful',
            why=f'Accounted for in the case file: {evidence}',
            estimated_minutes_saved=pb.estimated_minutes_saved if pb else 45,
        ))
    if not any(task.category == 'benefits' for task in tasks):
        pb = PLAYBOOKS['benefits_scan']
        tasks.append(PlannedTask(title=pb.title,category=pb.category,playbook_id=pb.id,
                                 risk=pb.risk,why='Check for benefits, refunds, and money owed to the family.',
                                 estimated_minutes_saved=pb.estimated_minutes_saved))
    tasks.sort(key=lambda task: (0 if task.category == 'identity' else 1 if task.category in ('insurance','government') else 2))
    return TaskPlan(tasks=tasks)
