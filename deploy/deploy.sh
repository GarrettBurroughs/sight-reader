#!/usr/bin/env bash
# Deploy an image to an environment's Cloud Run service, then wait until it reports healthy.
# Used by both workflows, so staging and prod get identical settings.
#
#   deploy/deploy.sh staging|prod IMAGE@sha256:... VERSION
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

ENV=$1 IMAGE_REF=$2 VERSION=$3
[[ $ENV == staging || $ENV == prod ]] || { echo "env must be staging or prod" >&2; exit 1; }
SERVICE=$(service_name "$ENV")

# max-instances 1: a single writer for the SQLite database (the lock in persistence.py covers the
# brief overlap while a new revision takes over). No CPU throttling: Litestream keeps syncing
# between requests. min-instances 0: scales to zero when you're not practising.
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --image "$IMAGE_REF" \
  --service-account "$(runtime_sa "$ENV")" \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 --no-cpu-throttling --cpu 1 --memory 1Gi \
  --concurrency 40 --timeout 60 --execution-environment gen2 \
  --set-env-vars "SIGHTREADER_BUCKET=$(data_bucket "$ENV"),SIGHTREADER_VERSION=${VERSION}" \
  --set-secrets "SIGHTREADER_PASSWORD=$(password_secret "$ENV"):latest,SIGHTREADER_SESSION_KEY=$(session_secret "$ENV"):latest" \
  --labels "app=sight-reader,env=$ENV" \
  --quiet

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')
echo "Deployed $VERSION to $URL; waiting for the database to be ready..."
for _ in $(seq 1 30); do
  if curl -fsS "$URL/api/health" | grep -q '"ready":true'; then
    curl -fsS "$URL/api/health"; echo
    echo "url=$URL" >> "${GITHUB_OUTPUT:-/dev/null}"
    exit 0
  fi
  sleep 4
done
echo "Not healthy after 2 minutes:" >&2
curl -sS "$URL/api/health" >&2 || true
exit 1
