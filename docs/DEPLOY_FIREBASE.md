# Hosting the live demo with a clean URL (Cloud Run + optional `*.web.app`)

Epilogue is a Python server (FastAPI + background agent threads + SQLite), so
static hosting alone can't run it. The deployment is **Google Cloud Run**
(runs the container, holds your API key as an env var), optionally fronted by
**Firebase Hosting** for the clean `https://<project>.web.app` URL.

Everything is automated in one interactive script:

```bash
./deploy.sh
```

## The only manual steps (Google requires a human for these, ~5 min once)

1. Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install), then `gcloud auth login`.
2. Create a GCP project **with billing enabled**:
   [console.cloud.google.com/projectcreate](https://console.cloud.google.com/projectcreate) →
   then Billing → link an account. (Cloud Run stays inside the free tier for a
   demo; the only real spend is your OpenAI usage.)
3. *Optional, for the clean `*.web.app` URL*: `npm i -g firebase-tools` and `firebase login`.

Then run `./deploy.sh` from the repo root. It asks for the project id and your
OpenAI key (hidden input), enables the required APIs, builds the container
with Cloud Build, deploys Cloud Run (`min-instances=1` keeps the case clock
warm), optionally wires Firebase Hosting, and prints your URL(s) plus the
generated **access code**.

> **About the exact name `epilogue.web.app`:** the `*.web.app` subdomain equals
> your **project ID**, and short IDs like `epilogue` are usually taken. Pick
> `epilogue-demo` / `try-epilogue` / etc. — your URL becomes
> `epilogue-demo.web.app`. Without Firebase you still get a clean HTTPS Cloud
> Run URL either way.

## Security & cost posture

- **The API key never enters the repo or the client** — it lives only as a
  Cloud Run environment variable.
- **The access code gates every credit-spending action** (starting a case,
  advancing the clock, answering decisions). Anyone can *look*; only people
  with the code can make the agent work. Give judges the code in Devpost's
  private testing-notes field.
- **Cap the key**: set a monthly usage limit at platform.openai.com →
  Settings → Limits ($5 is generous — a full case on `gpt-4.1-mini` runs
  well under $1). Rotate the key after the hackathon.
- **State is a demo, not a database**: SQLite lives in the container; one case
  at a time by design; redeploys reset it.

## Verify

```bash
curl https://<your-url>/api/state     # → {"case": null, ...}
```

Open the URL, click **Use the demo case → Begin**, enter the access code when
asked (remembered per browser), and watch the live feed.
