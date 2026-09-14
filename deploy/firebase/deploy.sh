#!/usr/bin/env bash
# Deploy Epilogue to Cloud Run behind Firebase Hosting (clean *.web.app URL).
#
# Prereqs (one-time, ~5 min):
#   1. https://console.firebase.google.com → Add project → pick an ID like
#      "epilogue-demo" (the ID becomes your URL: epilogue-demo.web.app).
#      Enable billing (Blaze) — required for Cloud Run; the demo runs in
#      free-tier amounts.
#   2. Install CLIs:  npm i -g firebase-tools   and   gcloud CLI
#   3. Log in:        firebase login            and   gcloud auth login
#
# Then, from the REPO ROOT:
#   PROJECT_ID=epilogue-demo \
#   OPENAI_API_KEY=sk-…      \
#   EPILOGUE_ACCESS_CODE=some-secret-word \
#   bash deploy/firebase/deploy.sh
#
# The API key travels ONLY as a Cloud Run environment variable — it is never
# in the repo, the image layers you push are private to your project, and the
# access code stops strangers from spending your credits through the UI.

set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID (your Firebase/GCP project id)}"
: "${OPENAI_API_KEY:?set OPENAI_API_KEY}"
REGION="${REGION:-us-central1}"
MODEL_ID="${EPILOGUE_MODEL_ID:-gpt-4.1-mini}"
ACCESS_CODE="${EPILOGUE_ACCESS_CODE:-}"

gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Building container"
gcloud builds submit --tag "gcr.io/$PROJECT_ID/epilogue" -f deploy/Dockerfile . 2>/dev/null \
  || gcloud builds submit --tag "gcr.io/$PROJECT_ID/epilogue" --config <(cat <<EOF
steps:
- name: gcr.io/cloud-builders/docker
  args: [build, -f, deploy/Dockerfile, -t, gcr.io/$PROJECT_ID/epilogue, .]
images: [gcr.io/$PROJECT_ID/epilogue]
EOF
) .

echo "==> Deploying to Cloud Run"
gcloud run deploy epilogue \
  --image "gcr.io/$PROJECT_ID/epilogue" \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --memory 1Gi \
  --set-env-vars "EPILOGUE_MODEL_PROVIDER=openai,EPILOGUE_MODEL_ID=$MODEL_ID,OPENAI_API_KEY=$OPENAI_API_KEY,EPILOGUE_ACCESS_CODE=$ACCESS_CODE,EPILOGUE_MAX_STEWARD_RUNS=5"

echo "==> Wiring Firebase Hosting → Cloud Run"
cd deploy/firebase
mkdir -p public
firebase use "$PROJECT_ID"
firebase deploy --only hosting

echo
echo "Done. Your demo is live at: https://$PROJECT_ID.web.app"
echo "(min-instances=1 keeps the case clock warm; SQLite state resets on redeploy — it's a demo.)"
