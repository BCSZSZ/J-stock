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
- `UPDATE_AUX_DATA` (used by manual/re-dispatch flows; scheduled daily dispatch currently forces `false` in SAM)
- `WORKER_MEMORY_MB` (example: `2048`)
- `MONITOR_LIST_S3_URI` (example: `s3://jsa-main-ops-xxxx/config/monitor_list.json`)
- `PRODUCTION_MONITOR_LIST_S3_URI` (optional; used only by `DailyNoFetchFunction` for signal generation. Example: `s3://bcszsz-ai-j-stock-bucket/prod/ops/config/production_monitor_list.json`)
- `DATA_S3_PREFIX` (example: `s3://bcszsz-ai-j-stock-bucket/prod/data`)
- `OPS_S3_PREFIX` (example: `s3://bcszsz-ai-j-stock-bucket/prod/ops`)
- `NOTIFY_EMAIL` (example: `you@example.com`)
- `PRODUCTION_CAPACITY_REGIME_MODE` (optional; one of `off`, `shadow`, `enforce`)

The production cron expressions are currently resolved from `infra/sam/samconfig.toml` during deploy. They are not sourced from GitHub repository variables.

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
- Scheduled daily fetch updates `raw_prices + features + benchmark`.
- `MONITOR_LIST_S3_URI` drives the fetch/readiness universe, together with the latest sector-pool CSV under `DATA_S3_PREFIX/universe/sector_pool/`.
- `DailyNoFetchFunction` can use a different production signal pool via `PRODUCTION_MONITOR_LIST_S3_URI`.
- If `PRODUCTION_MONITOR_LIST_S3_URI` is unset, `DailyNoFetchFunction` falls back to `{OPS_S3_PREFIX}/config/production_monitor_list.json`, then finally to `MONITOR_LIST_S3_URI`.
- `PRODUCTION_CAPACITY_REGIME_MODE=shadow` enables tier diagnostics only; `enforce` turns on actual tier-based position count and order-cap sizing in AWS production daily runs.
- `raw_trades + raw_financials` are only refreshed when `update_aux_data=true`.
- The AWS fetch worker now refreshes TOPIX before ticker ETL, then uploads `benchmarks/topix_daily.parquet` back to `DATA_S3_PREFIX`.
- The readiness gate still requires the benchmark object JST date to match `run_date`; readiness artifacts now include `benchmark_key`, `benchmark_exists`, `benchmark_last_modified_jst`, and `benchmark_error_code`.
- If you ever need a lightweight mode, you can temporarily set `UPDATE_AUX_DATA=false`.
- Notifications use SNS email subscription (no sender identity setup required).
- After first deploy, SNS sends a confirmation email. Click `Confirm subscription` once to start receiving alerts.

## Current Production Schedule

Effective schedule for `jsa-main-sqs` as currently deployed from `infra/sam/samconfig.toml`:

- Dispatch fetch jobs: 18:00 JST (`cron(0 9 ? * MON-FRI *)`)
- Validation attempt `1900`: 19:00 JST (`cron(0 10 ? * MON-FRI *)`)
- Validation attempt `1930`: 19:30 JST (`cron(30 10 ? * MON-FRI *)`)
- Daily no-fetch run: 21:00 JST (`cron(0 12 ? * MON-FRI *)`)

If you need to change these times, update `infra/sam/samconfig.toml` and redeploy. Changing GitHub variables alone will not change the live Scheduler rules.

## AWS Daily Recovery Checklist

If the daily run is skipped because readiness failed:

1. Resolve live function/resource names from CloudFormation:

```bash
aws cloudformation describe-stacks --stack-name jsa-main-sqs --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
```

2. Inspect readiness artifacts for the affected date:

```bash
aws s3 cp s3://<OPS_BUCKET>/<OPS_PREFIX>/run_status/date=YYYY-MM-DD/readiness.json -
aws s3 cp s3://<OPS_BUCKET>/<OPS_PREFIX>/run_status/date=YYYY-MM-DD/readiness_attempt=1900.json -
aws s3 cp s3://<OPS_BUCKET>/<OPS_PREFIX>/run_status/date=YYYY-MM-DD/readiness_attempt=1930.json -
```

3. Inspect the benchmark object directly:

```bash
aws s3api head-object --bucket <DATA_BUCKET> --key <DATA_PREFIX>/benchmarks/topix_daily.parquet
```

4. If benchmark data was repaired or backfilled, re-run readiness manually:

```bash
aws lambda invoke --function-name <ValidateReadinessFunctionName> --payload '{"run_date":"YYYY-MM-DD","attempt":"manual","force":true}' out.json
```

5. Only after readiness is `ready=true`, invoke daily no-fetch manually:

```bash
aws lambda invoke --function-name <DailyNoFetchFunctionName> --payload '{"run_date":"YYYY-MM-DD","force":true}' out.json
```

If AWS CLI says the token is expired or missing, sign in first and then rerun the commands above.

## Universe Sync Notes

- Local reference counts in this repo are currently: `data/monitor_list.json = 120`, `data/production_monitor_list.json = 62`.
- If you want AWS fetch/readiness to follow the latest 120-name monitor pool, update the S3 object referenced by `MONITOR_LIST_S3_URI`.
- If you want AWS signal generation to follow a separate production pool, upload that JSON to S3 and point `PRODUCTION_MONITOR_LIST_S3_URI` at it.
- The existing `tools/sync_ops_state_s3.py push` flow uploads `production_monitor_list.json`, but it does not upload the generic 120-name `monitor_list.json` or the latest sector-pool CSVs. Those still need a separate upload step if AWS should consume the newest selection artifacts.

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
