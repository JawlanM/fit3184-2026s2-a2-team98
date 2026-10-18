# fit3184-2026s2-a2-team98

Aussie EcoGuard: multi-cloud serverless pest and pet monitoring (AWS + GCP).

## Layout

| Path | Owner | Contents |
|---|---|---|
| `backend/template.yaml` | A | SAM template: Cognito, API Gateway, DynamoDB, S3, SNS, all Lambdas |
| `backend/layers/common/` | shared | `common/` package used by every Lambda (see below) |
| `backend/functions/` | all | One folder per Lambda; each owner adds their own |
| `backend/tests/` | all | pytest + moto, runs without an AWS account |
| `config/labels.json` | shared | The one species list (names, synonyms, Rekognition names) |
| `scripts/` | A | `build_layer.py`, `sync_labels.py`, `smoke_test.py` |
| `ml/` | B | Cloud Run inference service (FastAPI) |
| `frontend/` | C | React + Vite + Amplify Auth |
| `docs/` | all | API contract, report material, `evidence/` screenshots |
| `postman/` | A | Postman collection for A's routes |

### The `common` layer

| Module | Use it for |
|---|---|
| `queries.py` | `find_by_tags`, `find_by_species`, `full_size_for_thumbnail`. Lex fulfilment calls these directly. |
| `schemas.py` | Pydantic request/response models matching the contract |
| `files.py` | Read `EcoGuardFiles` items and turn them into `FileItem` with presigned view links |
| `urls.py` | Canonical URL <-> `fileId` |
| `labels.py` | `normalise("Cane Toads") -> "cane toad"`, `from_rekognition("Fox") -> "fox"` |
| `expr.py` | Placeholders for DynamoDB expressions (`count`, `status`, `feral pig`) |
| `errors.py`, `web.py` | `create_app()`, `make_handler(app)`, `caller(request)`, the contract error shape |
| `m2m.py` | `access_token()` for the dispatcher's call to Cloud Run (cached for the hour) |

## Deployed stack (ap-southeast-2)

| Output | Value |
|---|---|
| API base URL | `https://2o67myf09f.execute-api.ap-southeast-2.amazonaws.com/prod` |
| User pool ID | `ap-southeast-2_kkyRmOxeA` |
| Web client ID (Amplify) | `1van5pb6fs3f3a9bmto9hjgld` |
| JWT issuer (Cloud Run check) | `https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_kkyRmOxeA` |
| M2M secret | `ecoguard/m2m-client` (clientId, clientSecret, tokenUrl, scope `ecoguard/detect`) |
| Buckets | `ecoguard-media-946695875842`, `ecoguard-thumbs-946695875842` |
| Tables | `EcoGuardFiles` (stream on), `EcoGuardTagIndex`, `EcoGuardSubscriptions` |

Full list: `aws cloudformation describe-stacks --stack-name ecoguard --region ap-southeast-2 --query "Stacks[0].Outputs"`.

## Run the tests (no AWS needed)

```bash
pip install -r backend/requirements-dev.txt
cd backend
python -m pytest tests -q
```

## Deploy the AWS backend

Lambda runs Linux, so the layer is built with Linux wheels. No Docker needed.

```bash
python scripts/build_layer.py      # -> backend/build/layer (also copies labels.json)
cd backend
sam build
sam deploy                         # settings come from samconfig.toml
cd ..
python scripts/smoke_test.py       # 32 checks against the live API, cleans up after itself
```

`python scripts/smoke_test.py --keep` leaves a seeded fox file and two test users in place for trying the frontend or Postman.

To let the CloudFront site call the API instead of localhost:

```bash
sam deploy --parameter-overrides AllowedOrigin=https://dxxxx.cloudfront.net WebAppUrl=https://dxxxx.cloudfront.net
```

## Adding a Lambda (B and C)

Copy the `QueryLogGroup` / `QueryRole` / `QueryFunction` block in `template.yaml`:

- give the function its own log group and its own `Role:` (SAM then adds no `*` policies),
- list only the actions it calls, on only our resources,
- HTTP routes: `RestApiId: !Ref EcoGuardApi`; the Cognito authorizer applies automatically,
- FastAPI apps: `app = web.create_app()` and `handler = web.make_handler(app)` give the contract's error shape and CORS headers.

## Rules

- Work on a feature branch, open a PR to `main`, and have it reviewed (A reviews B, B reviews C, C reviews A).
- No secrets in the repo. Use Secrets Manager or GitHub Secrets.
- Changes to `docs/api-contract.md` go through a PR that all three members approve.
