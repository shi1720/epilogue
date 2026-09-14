"""Opt-in live model evaluation against a running LOCAL demo server.

Uses only the built-in fictional case. Reset is explicit via --reset.
Never use this against a workspace containing a real family's case.
"""
import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--reset', action='store_true')
parser.add_argument('--days', type=int, default=12)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
client = httpx.Client(base_url='http://127.0.0.1:8123', timeout=30)


def post(path, body=None):
    response = client.post(path,json=body or {})
    response.raise_for_status()
    return response.json()


def idle():
    deadline=time.monotonic()+1000
    while time.monotonic()<deadline:
        state=client.get('/api/state').json()
        if state['status']=='idle':
            print(json.dumps({k:state.get(k) for k in ['status','stats','error','budget']}),flush=True)
            if state.get('error'):
                raise AssertionError(state['error'])
            return state
        time.sleep(3)
    raise AssertionError('Agent session exceeded the test timeout')


if args.reset:
    post('/api/reset')
    post('/api/case',client.get('/api/seed').json())
state=idle()
assert len(state['tasks'])>=15
assert {'beacon_mutual','fed_benefits','pixelvault','equifax_sim','experian_sim','transunion_sim'} <= {t['institution_id'] for t in state['tasks']}
for day in range(args.days+1):
    # Act as the fictional survivor, exercising the real decision gate and reaction.
    for _ in range(8):
        decisions=[d for d in state['decisions'] if d['status']=='open']
        if not decisions:
            break
        d=decisions[0]
        options=[o for o in d['options'] if o.get('authorizes')]
        chosen=next((o for o in options if o['id']==d.get('recommendation')), options[0])
        print('DECISION',d['question'],'=>',chosen['label'],flush=True)
        post(f"/api/decisions/{d['id']}/resolve",{'option_id':chosen['id'],'note':'Fictional live evaluation: preserve memories and keep the house powered.'})
        state=idle()
    if day<args.days:
        print('ADVANCE',day+1,flush=True)
        post('/api/clock/advance',{'days':1})
        state=idle()
result=client.get('/api/export').json()
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,indent=2))
assert result['stats']['settled']>=8, result['stats']
assert any(m['direction']=='outbound' for m in result['mail'])
assert any(m['direction']=='inbound' for m in result['mail'])
assert any(d['status']=='resolved' for d in result['decisions'])
assert result['weekly_note']
assert result['budget']['spent_usd']<3
assert result['budget']['reserved_usd']==0
print('LIVE E2E PASSED',flush=True)
