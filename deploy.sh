#!/usr/bin/env bash
# ============================================================================
# Epilogue — one-command cloud deploy (Google Cloud Run, optional *.web.app URL)
#
#   ./deploy.sh
#
# It asks for anything it needs, does everything else, and prints your URL.
#
# One-time prerequisites (~5 min, only the parts Google requires a human for):
#   1. gcloud CLI installed  → https://cloud.google.com/sdk/docs/install
#   2. gcloud auth login
#   3. A GCP project WITH BILLING enabled → https://console.cloud.google.com/projectcreate
#      (billing: console → Billing → link account; Cloud Run itself is
#       free-tier for this demo — the only real spend is your OpenAI usage)
#   Optional, for the clean https://<project>.web.app URL:
#   4. npm i -g firebase-tools   and   firebase login
#
# Your API key is sent ONLY to Cloud Run as an environment variable — it is
# never written to the repo or the client. The access code gates every action
# that spends credits, so the public URL is safe to share.
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mXX  %s\033[0m\n' "$*"; exit 1; }

command -v gcloud >/dev/null || fail "gcloud CLI not found — install: https://cloud.google.com/sdk/docs/install"
gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . \
  || fail "Not logged in — run:  gcloud auth login"

# ---- gather inputs (env vars override; otherwise ask) ----------------------
PROJECT_ID="${PROJECT_ID:-}"
if [ -z "$PROJECT_ID" ]; then
  DEFAULT_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
  read -r -p "GCP project id [${DEFAULT_PROJECT:-none}]: " PROJECT_ID
  PROJECT_ID="${PROJECT_ID:-$DEFAULT_PROJECT}"
fi
[ -n "$PROJECT_ID" ] || fail "A project id is required (create one at console.cloud.google.com/projectcreate)"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  read -r -s -p "OpenAI API key (input hidden): " OPENAI_API_KEY; echo
fi
[ -n "$OPENAI_API_KEY" ] || fail "An OpenAI API key is required"

ACCESS_CODE="${EPILOGUE_ACCESS_CODE:-}"
if [ -z "$ACCESS_CODE" ]; then
  ACCESS_CODE="epilogue-$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  say "Generated access code: $ACCESS_CODE  (share it with judges; it gates all credit-spending actions)"
fi

REGION="${REGION:-us-central1}"
MODEL_ID="${EPILOGUE_MODEL_ID:-gpt-4.1-mini}"

# ---- deploy ----------------------------------------------------------------
gcloud config set project "$PROJECT_ID" >/dev/null

say "Enabling required APIs (first run can take ~1 min)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

say "Building and deploying to Cloud Run (~3-5 min on first deploy)"
gcloud run deploy epilogue \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --memory 1Gi \
  --set-env-vars "EPILOGUE_MODEL_PROVIDER=openai,EPILOGUE_MODEL_ID=$MODEL_ID,OPENAI_API_KEY=$OPENAI_API_KEY,EPILOGUE_ACCESS_CODE=$ACCESS_CODE,EPILOGUE_MAX_STEWARD_RUNS=5"

RUN_URL="$(gcloud run services describe epilogue --region "$REGION" --format='value(status.url)')"
say "Live on Cloud Run: $RUN_URL"

# ---- optional: clean *.web.app URL via Firebase Hosting --------------------
if command -v firebase >/dev/null 2>&1; then
  read -r -p "Also wire the clean https://$PROJECT_ID.web.app URL via Firebase Hosting? [Y/n]: " WIRE
  if [ "${WIRE:-Y}" != "n" ] && [ "${WIRE:-Y}" != "N" ]; then
    firebase projects:list 2>/dev/null | grep -q "$PROJECT_ID" \
      || firebase projects:addfirebase "$PROJECT_ID" || true
    cd deploy/firebase
    mkdir -p public
    printf '{"projects": {"default": "%s"}}\n' "$PROJECT_ID" > .firebaserc
    firebase deploy --only hosting --project "$PROJECT_ID"
    say "Clean URL live: https://$PROJECT_ID.web.app"
    cd ../..
  fi
else
  echo "(Tip: for the clean https://$PROJECT_ID.web.app URL, install firebase-tools, 'firebase login', and re-run.)"
fi

say "Done. Access code for testers: $ACCESS_CODE"
echo "    Verify:  curl $RUN_URL/api/state"
echo "    Remember: set a spending cap on the OpenAI key, and rotate it after the hackathon."
