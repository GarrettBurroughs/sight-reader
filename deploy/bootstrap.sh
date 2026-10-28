#!/usr/bin/env bash
# One-time setup of everything the deployment needs in GCP and GitHub. Safe to re-run:
# each step skips what already exists. Run from the repo root:
#
#   deploy/bootstrap.sh
#
# Creates, in project $PROJECT ($REGION):
#   - APIs: Cloud Run, Artifact Registry, IAM, STS, Secret Manager, Storage
#   - Artifact Registry repo for images (keeps the 20 newest, and anything under 30 days old)
#   - Buckets: published libraries, and one Litestream bucket per environment
#   - Service accounts: one runtime account per environment, one deployer for GitHub Actions
#   - Workload Identity Federation so only $REPO_SLUG's Actions can act as the deployer (no keys)
#   - Secrets: app password (asked for) and session key (random) per environment
#   - GitHub repo variables the workflows read
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
gcloud config set project "$PROJECT" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')

step "Enabling APIs (takes a minute the first time)"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com secretmanager.googleapis.com storage.googleapis.com

step "Artifact Registry repo $AR_REPO"
if ! gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" --location "$REGION" --repository-format docker \
    --description "Sight reader app images"
fi
cat > /tmp/sr-cleanup-policy.json <<'JSON'
[
  {"name": "keep-newest-20", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 20}},
  {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"tagState": "ANY", "olderThan": "30d"}}
]
JSON
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location "$REGION" \
  --policy /tmp/sr-cleanup-policy.json --no-dry-run >/dev/null

make_bucket() {
  if ! gcloud storage buckets describe "gs://$1" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://$1" --location "$REGION" --uniform-bucket-level-access \
      --public-access-prevention
  fi
}

step "Buckets"
make_bucket "$LIBRARY_BUCKET"
for env in staging prod; do make_bucket "$(data_bucket $env)"; done

make_sa() {  # name, display name
  if ! gcloud iam service-accounts describe "$1@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$1" --display-name "$2"
  fi
}

step "Service accounts"
make_sa sr-deployer "Sight reader: GitHub Actions deployer"
for env in staging prod; do make_sa "sr-run-$env" "Sight reader: $env runtime"; done

step "Secrets (password per environment, random session key)"
for env in staging prod; do
  if ! gcloud secrets describe "$(password_secret $env)" >/dev/null 2>&1; then
    read -rsp "Password for $env: " pw; echo
    printf '%s' "$pw" | gcloud secrets create "$(password_secret $env)" --replication-policy automatic --data-file -
  fi
  if ! gcloud secrets describe "$(session_secret $env)" >/dev/null 2>&1; then
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' \
      | gcloud secrets create "$(session_secret $env)" --replication-policy automatic --data-file -
  fi
done

step "Permissions: runtime accounts (own bucket and secrets only)"
for env in staging prod; do
  sa="serviceAccount:$(runtime_sa $env)"
  gcloud storage buckets add-iam-policy-binding "gs://$(data_bucket $env)" --member "$sa" \
    --role roles/storage.objectAdmin >/dev/null
  for secret in "$(password_secret $env)" "$(session_secret $env)"; do
    gcloud secrets add-iam-policy-binding "$secret" --member "$sa" --role roles/secretmanager.secretAccessor >/dev/null
  done
done

step "Permissions: deployer (deploy Cloud Run, push images, read libraries)"
deployer="serviceAccount:$DEPLOYER_SA"
gcloud projects add-iam-policy-binding "$PROJECT" --member "$deployer" --role roles/run.admin \
  --condition None >/dev/null
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$REGION" --member "$deployer" \
  --role roles/artifactregistry.writer >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$LIBRARY_BUCKET" --member "$deployer" \
  --role roles/storage.objectViewer >/dev/null
for env in staging prod; do  # deploying a service that runs as these accounts
  gcloud iam service-accounts add-iam-policy-binding "$(runtime_sa $env)" --member "$deployer" \
    --role roles/iam.serviceAccountUser >/dev/null
done

step "Workload Identity Federation for $REPO_SLUG"
if ! gcloud iam workload-identity-pools describe "$WIF_POOL" --location global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$WIF_POOL" --location global --display-name "GitHub Actions"
fi
if ! gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" --location global \
    --workload-identity-pool "$WIF_POOL" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" --location global \
    --workload-identity-pool "$WIF_POOL" --display-name "GitHub OIDC" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository == '${REPO_SLUG}'"
fi
POOL_ID="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${REPO_SLUG}" >/dev/null

step "GitHub repo variables"
gh variable set GCP_WIF_PROVIDER --repo "$REPO_SLUG" --body "${POOL_ID}/providers/${WIF_PROVIDER}"
gh variable set GCP_DEPLOYER_SA --repo "$REPO_SLUG" --body "$DEPLOYER_SA"

step "Done"
echo "Next: deploy/publish-library.sh, commit library.version, and push. Staging deploys from main."
