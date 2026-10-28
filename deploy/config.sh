# Shared names for the GCP deployment. Sourced by the other deploy scripts and by CI.
PROJECT=gburroughs
REGION=us-east1
REPO_SLUG=GarrettBurroughs/sight-reader          # GitHub repo allowed to deploy

AR_REPO=sight-reader                              # Artifact Registry (Docker images)
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/app"
LIBRARY_BUCKET="${PROJECT}-sight-reader-library"  # published library versions
DEPLOYER_SA="sr-deployer@${PROJECT}.iam.gserviceaccount.com"
WIF_POOL=github
WIF_PROVIDER=github-oidc

# Per environment ($1 = staging | prod)
service_name()  { echo "sight-reader-$1"; }
data_bucket()   { echo "${PROJECT}-sight-reader-$1"; }   # Litestream replica + lock
runtime_sa()    { echo "sr-run-$1@${PROJECT}.iam.gserviceaccount.com"; }
password_secret() { echo "sight-reader-password-$1"; }
session_secret()  { echo "sight-reader-session-key-$1"; }
