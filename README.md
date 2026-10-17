# fit3184-2026s2-a2-team98

Aussie EcoGuard: multi-cloud serverless pest and pet monitoring (AWS + GCP).

## Layout

| Path | Owner | Contents |
|---|---|---|
| `backend/template.yaml` | A | SAM template: Cognito, API Gateway, DynamoDB, S3, all Lambdas |
| `backend/layers/common/` | shared | `common/schemas.py` (Pydantic), `common/queries.py` (query logic, also used by Lex) |
| `backend/functions/` | all | One folder per Lambda; each owner adds their own |
| `ml/` | B | Cloud Run inference service (FastAPI) |
| `frontend/` | C | React + Vite + Amplify Auth |
| `docs/` | all | API contract, task split, report material, `evidence/` screenshots |
| `postman/` | A | Postman collection covering every endpoint |

## Deploy the AWS backend

```bash
cd backend
sam build
sam deploy          # settings come from samconfig.toml
```

## Rules

- Work on a feature branch, open a PR to `main`, and have it reviewed (A reviews B, B reviews C, C reviews A).
- No secrets in the repo. Use Secrets Manager or GitHub Secrets.
- Changes to `docs/api-contract.md` go through a PR that all three members approve.
