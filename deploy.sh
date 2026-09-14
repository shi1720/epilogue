#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v gcloud >/dev/null || { echo 'Run this script in Google Cloud Shell (gcloud is required).'; exit 1; }
command -v firebase >/dev/null || { echo 'Install the Firebase CLI: npm install -g firebase-tools'; exit 1; }
exec python3 scripts/deploy_firebase.py
