# Deploy the private live demo

Epilogue uses Firebase Hosting for the clean `*.web.app` address, Firebase Authentication for Google sign-in, a dedicated Firestore database named `epilogue` for case records and usage, and Cloud Run for the Python agent. A new GCP project is not needed. Firebase Hosting site IDs are globally unique; the deployment tries `epilogue`, then `epilogue-agent`, then `epilogue-shi1720` if needed.

From the existing project's authenticated Google Cloud Shell:

```bash
git pull
PROJECT_ID=gen-lang-client-0444960702 SITE_ID=epilogue ./deploy.sh
```

The migration script expects an existing Cloud Run service named `epilogue`. It preserves other Firebase apps and their authorized domains, adds a dedicated Epilogue web app, and deploys only the chosen Hosting site. The original project URL continues to route to the updated service. Google sign-in must already be configured on the project (the existing OfferLoop configuration can be shared).

The script migrates the existing server-side OpenAI key to Secret Manager, removes the old access-code gate, installs the OpenAI provider in the container, and verifies the deployed health endpoint. To use a replacement key, supply `OPENAI_API_KEY_FILE` pointing to a private file on the deployment machine. The key is read into memory and piped to Secret Manager; it is never placed in the public frontend, repository, or command-line arguments.

## Allowances and limits

- Each verified Google account gets a **$3 lifetime testing allowance**; no payment method is collected by Epilogue.
- A **$30 aggregate host limit** bounds the public demo. Set `EPILOGUE_ACCOUNT_BUDGET_USD` / `EPILOGUE_GLOBAL_BUDGET_USD` when deploying to change these amounts.
- These are app-enforced allowances against the host's OpenAI key, not purchased OpenAI credits. The underlying OpenAI project must have working billing.
- Every request reserves an upper-bound estimate before calling OpenAI. Reported prompt, cached prompt, and completion tokens reconcile that reservation. Unknown usage after an interrupted request is conservatively charged; crash reservations remain unavailable rather than allowing an overspend.
- The hosted model is `gpt-4.1-mini` with a 4,096-token output cap. Pricing constants live in `src/epilogue/budget.py`; enabling another model requires an explicit, verified price mapping.
- Up to three work sessions can run at once per instance. Each session pauses after 100 model calls or 15 minutes. Continue resumes saved work. Clock jumps may pause partway through; the displayed date records progress.
- Resetting a case, reloading the app, signing out, or restarting the service does not refill the allowance.

## Runtime and persistence

Cloud Run is configured for one warm instance with CPU available between requests, because the agent works after an HTTP action returns. This incurs ongoing Cloud Run hosting charges independently of OpenAI allowances. The account credit meter covers model usage only.

Each ledger row is persisted in Firestore before local acknowledgement. A transactional per-account lease prevents overlapping runs across deployment revisions. A heartbeat renews that lease; an interrupted worker becomes resumable after its three-minute lease expires. Each account has its own ledger namespace, and a new-case action selects a new generation without resetting account usage.

All private API routes, including correspondence, export, and the event feed, require a verified session. Firebase Hosting forwards only the specially named `__session` cookie; it is HttpOnly, Secure, and SameSite=Lax. Responses use `private, no-store`, and mutations require an origin check plus a custom request header. The browser never receives the OpenAI API key. Firebase's browser configuration contains public project identifiers, not the model credential.

All institutions are **simulated**. No real bank, subscription, government, insurance, or credit bureau integrations are enabled. Inputs are sent to OpenAI for processing, so use fictional data when testing.

## Verification

```bash
pip install -e '.[dev,hosting]'
ruff check src tests
pytest -m 'not live'
node --check web/app.js
bash -n deploy.sh
```

For an opt-in live evaluation, run a local server with `EPILOGUE_MODEL_PROVIDER=openai`, `EPILOGUE_MODEL_ID=gpt-4.1-mini`, and `OPENAI_API_KEY` in its environment, then:

```bash
python scripts/live_e2e.py --reset --days 12 --output live-case.json
```

This explicitly resets the local test workspace and runs the fictional Mitchell case. It checks coverage, decisions, simulated outbound and inbound mail, settled matters, a weekly note, and metered spend. Do not use it against real case data.

Official references: [multiple Hosting sites](https://firebase.google.com/docs/hosting/multisites), [session cookies](https://firebase.google.com/docs/auth/admin/manage-cookies), [Hosting cookie handling](https://firebase.google.com/docs/hosting/manage-cache), [GPT-4.1 mini pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
