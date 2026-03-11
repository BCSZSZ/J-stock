# GitHub -> AWS CI/CD Setup (OIDC + SAM)

## Goal

Push code from any terminal to GitHub and have AWS stack auto-updated.

## Workflows added

- `.github/workflows/deploy-prod.yml`
  - Trigger: push to `main`
  - Deploy stack: `jsa-main-sqs`

## Required GitHub Variables

Set repository/environment variables:

- `AWS_REGION` (example: `ap-northeast-1`)
- `TICKERS_PER_JOB` (example: `100`)
- `UPDATE_AUX_DATA` (`true` recommended; daily updates all layers)
- `WORKER_MEMORY_MB` (example: `2048`)
- `MONITOR_LIST_S3_URI` (example: `s3://jsa-main-ops-xxxx/config/monitor_list.json`)
- `DATA_S3_PREFIX` (example: `s3://bcszsz-ai-j-stock-bucket/prod/data`)
- `OPS_S3_PREFIX` (example: `s3://bcszsz-ai-j-stock-bucket/prod/ops`)
- `SCHEDULE_EXPRESSION` (example: `cron(0 9 ? * MON-FRI *)`)
- `DAILY_NO_FETCH_SCHEDULE_EXPRESSION` (example: `cron(0 11 ? * MON-FRI *)`)
- `NOTIFY_EMAIL` (example: `you@example.com`)

## Required GitHub Secrets

Set repository/environment secrets:

- `AWS_ROLE_TO_ASSUME`
- `JQUANTS_API_KEY`

## AWS OIDC IAM trust policy example

Use this in IAM role trust policy (`sub` should match your repo + branch):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": [
            "repo:<OWNER>/<REPO>:ref:refs/heads/main"
          ]
        }
      }
    }
  ]
}
```

## IAM policy for deploy role (minimum practical)

Allow CloudFormation/S3/Lambda/SQS/Scheduler/IAM pass role operations required by SAM deploy.

Tip: start from AWS managed `PowerUserAccess` in a sandbox, then tighten to least privilege after first successful deployment.

## Behavior

- Any push to `main` auto-deploys main stack.
- `workflow_dispatch` allows manual trigger from GitHub UI.

## Notes

- This CI/CD is independent from whether all runtime features are complete.
- It guarantees your latest GitHub code is continuously synced to AWS infrastructure/functions.
- Daily default behavior: `raw_prices + features + benchmark + raw_trades + raw_financials` are all updated.
- If you ever need a lightweight mode, you can temporarily set `UPDATE_AUX_DATA=false`.
- Notifications use SNS email subscription (no sender identity setup required).
- After first deploy, SNS sends a confirmation email. Click `Confirm subscription` once to start receiving alerts.

## Local input -> S3 sync (recommended MLP)

After local manual input:

```powershell
.venv/Scripts/python.exe main.py production --input --manual --manual-file today.csv --yes
.venv/Scripts/python.exe tools/sync_ops_state_s3.py push --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops --config config.local.json
```

Then AWS can run daily no-fetch using synced state:

```powershell
aws lambda invoke --function-name jsa-main-sqs-DailyNoFetchFunction-<suffix> out.json
```
