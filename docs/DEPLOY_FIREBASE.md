# Hosting the live demo at a clean `*.web.app` URL

Epilogue is a Python server (FastAPI + background agent threads + SQLite), so
Firebase Hosting alone can't run it — the standard pattern is **Firebase
Hosting → Cloud Run**: Hosting owns the clean URL and proxies every request to
the container. That is exactly what `deploy/firebase/` sets up.

> **Heads-up on the exact name `epilogue.web.app`:** the `*.web.app` subdomain
> equals your Firebase **project ID**. Short IDs like `epilogue` are usually
> taken — if so, pick `epilogue-demo`, `epilogue-agent`, `try-epilogue`, …
> and your URL is `epilogue-demo.web.app` etc. (You can also attach any custom
> domain you own in Hosting → Add custom domain.)

## One-time setup (~5 minutes)

1. **Create the project**: [console.firebase.google.com](https://console.firebase.google.com)
   → *Add project* → enter your ID (this becomes the URL) → create.
   Upgrade it to the **Blaze** plan (required for Cloud Run; this demo stays
   in free-tier request volumes — the only real spend is your OpenAI usage).
2. **Install the CLIs**: `npm i -g firebase-tools` and the
   [gcloud CLI](https://cloud.google.com/sdk/docs/install).
3. **Sign in**: `firebase login` and `gcloud auth login`.

## Deploy (one command)

From the repository root:

```bash
PROJECT_ID=epilogue-demo \
OPENAI_API_KEY=sk-…yourkey… \
EPILOGUE_ACCESS_CODE=choose-a-secret-word \
bash deploy/firebase/deploy.sh
```

That builds the container with Cloud Build, deploys it to Cloud Run
(`min-instances=1` so the case clock stays warm), and points
`https://<PROJECT_ID>.web.app` at it.

## Security & cost posture (read this)

- **The API key never enters the repo or the client.** It lives only as a
  Cloud Run environment variable. Anyone can *view* the dashboard; the
  **access code** gates every action that spends model credits (starting a
  case, advancing the clock, answering decisions). Share the code with
  judges in your Devpost "testing instructions" field — Devpost has a
  private-notes field for exactly this.
- **Cap the spend at the source**: set a monthly usage limit on the OpenAI
  key (platform.openai.com → Settings → Limits). $5 is far more than a demo
  needs (a full case on `gpt-4.1-mini` runs well under $1).
- **State is a demo, not a database**: SQLite lives in the container, and one
  case at a time is by design. Redeploying resets it — which for a judged
  demo is a feature (`Reset` is also available in the API).
- **Rotate the key after the hackathon.**

## Verifying

```bash
curl https://<PROJECT_ID>.web.app/api/state          # → {"case": null, ...}
open https://<PROJECT_ID>.web.app                     # intake page
```

Enter the access code when the UI asks (first action only — it's remembered
in your browser).
