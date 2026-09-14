#!/usr/bin/env python3
"""Deploy the hosted demo without exposing API keys in argv, source, or browser bundles.

Run from an authenticated Cloud Shell: PROJECT_ID=... ./deploy.sh
Reuses an existing runtime key if OPENAI_API_KEY / OPENAI_API_KEY_FILE is absent.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = os.environ.get('PROJECT_ID', 'gen-lang-client-0444960702')
REGION = os.environ.get('REGION', 'us-central1')
SITE = os.environ.get('SITE_ID', 'epilogue')
SERVICE = os.environ.get('SERVICE_NAME', 'epilogue')
DATABASE = 'epilogue'
SECRET = 'epilogue-openai-api-key'


def run(*args, capture=False, input=None, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, input=input,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, check=False)
    if check and result.returncode:
        # Commands never include a secret, but cloud output may. Do not echo captured output.
        raise RuntimeError(f'{args[0]} {args[1]} failed (exit {result.returncode}). Check the cloud console.')
    return result


def cloud(*args, **kwargs):
    return run('gcloud', *args, '--project', PROJECT, **kwargs)


def google(path, method='GET', data=None):
    token = cloud('auth','print-access-token',capture=True).stdout.strip()
    request = urllib.request.Request(path,method=method,
        headers={'Authorization':'Bearer '+token,'x-goog-user-project':PROJECT,'Content-Type':'application/json'},
        data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Google administrative API errors contain configuration information, not our OpenAI key.
        raise RuntimeError(f'Google API {exc.code}: {exc.read().decode()[:800]}') from exc


def deploy():
    print('Preparing Firebase Hosting, a private Firestore database, and the OpenAI runtime.', flush=True)
    cloud('services','enable','run.googleapis.com','cloudbuild.googleapis.com','artifactregistry.googleapis.com',
          'firestore.googleapis.com','identitytoolkit.googleapis.com','secretmanager.googleapis.com')
    service = json.loads(cloud('run','services','describe',SERVICE,'--region',REGION,'--format=json',capture=True).stdout)
    service_account = service['spec']['template']['spec']['serviceAccountName']
    env = {v['name']:v.get('value') for v in service['spec']['template']['spec']['containers'][0].get('env',[])}
    key = os.environ.get('OPENAI_API_KEY')
    if os.environ.get('OPENAI_API_KEY_FILE'):
        key = pathlib.Path(os.environ['OPENAI_API_KEY_FILE']).read_text().strip()
    key = key or env.get('OPENAI_API_KEY')
    secret_exists = cloud('secrets','describe',SECRET,capture=True,check=False).returncode == 0
    if not secret_exists:
        if not key:
            raise RuntimeError('Set OPENAI_API_KEY_FILE to a local private key file before the first deployment.')
        cloud('secrets','create',SECRET,'--replication-policy=automatic',capture=True)
    if key:
        cloud('secrets','versions','add',SECRET,'--data-file=-',input=key,capture=True)
    del key
    cloud('secrets','add-iam-policy-binding',SECRET,'--member=serviceAccount:'+service_account,
          '--role=roles/secretmanager.secretAccessor',capture=True)
    databases = json.loads(cloud('firestore','databases','list','--format=json',capture=True).stdout)
    if not any(row['name'].endswith('/'+DATABASE) for row in databases):
        cloud('firestore','databases','create','--database='+DATABASE,'--location='+REGION,
              '--type=firestore-native','--delete-protection', '--quiet')
    # Existing runtime identity retains its existing IAM access; no broad project grants.
    print('Finding a clean Firebase site address…',flush=True)
    sites = json.loads(run('firebase','hosting:sites:list','--project',PROJECT,'--json',capture=True).stdout)['result']['sites']
    existing_sites = {row['name'].split('/')[-1] for row in sites}
    chosen = None
    for candidate in dict.fromkeys([SITE, 'epilogue-agent', 'epilogue-shi1720']):
        if candidate in existing_sites or run('firebase','hosting:sites:create',candidate,'--project',PROJECT,'--json',capture=True,check=False).returncode == 0:
            chosen = candidate
            break
    if not chosen:
        raise RuntimeError('The requested Firebase site names are unavailable. Set SITE_ID to another short name.')
    print('Hosting address: https://'+chosen+'.web.app',flush=True)
    apps = json.loads(run('firebase','apps:list','WEB','--project',PROJECT,'--json',capture=True).stdout)['result']
    webapp = next((a for a in apps if a.get('displayName') == 'Epilogue'),None)
    if webapp is None:
        webapp = json.loads(run('firebase','apps:create','WEB','Epilogue','--project',PROJECT,'--json',capture=True).stdout)['result']
    config = json.loads(run('firebase','apps:sdkconfig','WEB',webapp['appId'],'--project',PROJECT,'--json',capture=True).stdout)['result']['sdkConfig']
    if isinstance(config,str):
        config = json.loads(config)
    # Firebase returns apiKey, authDomain, projectId, etc. They are public app identifiers.
    config = {k:v for k,v in config.items() if k in ('apiKey','authDomain','projectId','appId','messagingSenderId','storageBucket')}
    auth_base = f'https://identitytoolkit.googleapis.com/admin/v2/projects/{PROJECT}/'
    current = google(auth_base+'config')
    domains = set(current.get('authorizedDomains',[])) | {chosen+'.web.app',chosen+'.firebaseapp.com',PROJECT+'.web.app'}
    google(auth_base+'config?updateMask=authorizedDomains','PATCH',{'authorizedDomains':sorted(domains)})
    provider = google(auth_base+'defaultSupportedIdpConfigs/google.com')
    if not provider.get('enabled'):
        google(auth_base+'defaultSupportedIdpConfigs/google.com?updateMask=enabled','PATCH',{'enabled':True})
    deployment_env = {
        'EPILOGUE_MODEL_PROVIDER':'openai','EPILOGUE_MODEL_ID':'gpt-4.1-mini','EPILOGUE_AUTH_MODE':'firebase',
        'EPILOGUE_FIREBASE_CONFIG':json.dumps(config),'EPILOGUE_FIRESTORE_DATABASE':DATABASE,
        'EPILOGUE_ACCOUNT_BUDGET_USD':os.environ.get('EPILOGUE_ACCOUNT_BUDGET_USD','3'),
        'EPILOGUE_GLOBAL_BUDGET_USD':os.environ.get('EPILOGUE_GLOBAL_BUDGET_USD','30'),
        'EPILOGUE_MAX_STEWARD_RUNS':'5','EPILOGUE_ALLOWED_ORIGINS':','.join('https://'+d for d in domains),
    }
    with tempfile.TemporaryDirectory(prefix='epilogue-deploy-') as tmp:
        env_file = pathlib.Path(tmp)/'env.json'
        env_file.write_text(json.dumps(deployment_env))
        print('Building and deploying the agent (background CPU enabled)…',flush=True)
        cloud('run','deploy',SERVICE,'--source','.', '--region',REGION, '--allow-unauthenticated',
              '--min-instances','1','--max-instances','1','--memory','1Gi','--concurrency','80',
              '--no-cpu-throttling','--timeout','3600','--env-vars-file',str(env_file),
              '--set-secrets',f'OPENAI_API_KEY={SECRET}:latest','--quiet')
        hosting_dir = pathlib.Path(tmp)/'hosting'
        hosting_dir.mkdir()
        (hosting_dir/'public').mkdir()
        # Only the new target is deployed. Other apps in this project are preserved.
        hosting = {'hosting':{'site':chosen,'public':'public','rewrites':[{'source':'**','run':{'serviceId':SERVICE,'region':REGION}}]}}
        config_path=hosting_dir/'firebase.json'
        config_path.write_text(json.dumps(hosting))
        run('firebase','deploy','--only','hosting','--project',PROJECT,'--config',str(config_path),'--non-interactive')
    url='https://'+chosen+'.web.app'
    # A newly created Hosting site can return 404 briefly while its first release propagates.
    for attempt in range(12):
        try:
            with urllib.request.urlopen(url+'/api/health',timeout=30) as response:
                health=json.load(response)
            if health.get('version')=='0.2.0' and health.get('auth')=='firebase':
                break
            raise RuntimeError('The site is not yet serving the new authenticated runtime.')
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            if attempt == 11:
                raise
            time.sleep(5)
    print('\nDeployed and verified: '+url,flush=True)
    print('Google sign-in • private case storage • $3 per account • $30 total host cap (configurable).')


if __name__=='__main__':
    deploy()
