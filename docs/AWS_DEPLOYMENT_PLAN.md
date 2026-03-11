# AWS Deployment Plan (Lambda + S3 + DynamoDB)

## 1. Scope and constraints

- Compute: AWS Lambda only (no EC2, no ECS)
- Storage: S3 as primary data lake and report store
- State: DynamoDB recommended for production state and trade history
- Scheduling: EventBridge Scheduler
- Notification: SNS email subscription
- CI/CD: GitHub Actions + OIDC deploy to AWS SAM stack
- J-Quants API key: environment variable only (`JQUANTS_API_KEY`), no extra secret service
- Networking: no NAT Gateway, Lambda runs as normal Lambda (no VPC required)

## 2. Current repo findings (as-is)

- Production and evaluation had hardcoded Google Drive defaults.
- Production config previously enforced `G:\\` path and would fail outside local machine.
- Daily workflow creates local output directories directly.
- No `.github/workflows` exists yet.
- Monitor universe list is ~62, but effective daily fetch scope is ~290 tickers.
- Local daily run takes about 20 minutes (confirmed).

## 3. Target architecture

- EventBridge Scheduler triggers Step Functions once per trading day.
- Step Functions orchestrates a split workflow:
  1. `PrepareUniverseLambda`: build fetch universe manifest
  2. `FetchShardLambda` via Map state: fetch/update subset of tickers per shard
  3. `GenerateSignalsLambda`: run signal generation on refreshed data
  4. `BuildReportLambda`: produce markdown/JSON summary
  5. `PersistAndNotifyLambda`: update DynamoDB state and publish SNS notification
- S3 stores parquet/features/report artifacts.
- DynamoDB stores state snapshot + append-only trade/cash events.

## 3.1 Alternative without Step Functions

You can avoid Step Functions by using:

- EventBridge Scheduler -> `DispatchFetchJobsLambda`
- `DispatchFetchJobsLambda` splits monitor list into jobs (100 tickers/job by default)
- Jobs are pushed to SQS queue
- `FetchWorkerLambda` is triggered by SQS and processes one job at a time

Reference SAM template: `infra/sam/template-sqs.yaml`

Tradeoffs:

- Pros: simpler orchestration and lower service count
- Pros: keeps request pace controllable under API limit (60 req/min)
- Cons: no built-in DAG/state visualization like Step Functions
- Cons: completion coordination for "all jobs done" requires extra mechanism

Recommended no-SFN coordination:

- Keep fetch fan-out in SQS workers
- Trigger signal/report in a separate scheduled Lambda with a delay (e.g., +20 to +40 min)
- Or use DynamoDB run-tracker counter (`expected_jobs`, `completed_jobs`) and start report when equal

## 4. S3 layout proposal

- `s3://<DataLakeBucket>/raw_prices/ticker=7974/data.parquet`
- `s3://<DataLakeBucket>/features/ticker=7974/data.parquet`
- `s3://<DataLakeBucket>/raw_trades/ticker=7974/data.parquet`
- `s3://<DataLakeBucket>/raw_financials/ticker=7974/data.parquet`
- `s3://<DataLakeBucket>/benchmarks/topix_daily.parquet`
- `s3://<OpsBucket>/signals/date=YYYY-MM-DD/group=group_main.json`
- `s3://<OpsBucket>/reports/date=YYYY-MM-DD/group=group_main.md`
- `s3://<OpsBucket>/state/*.json` (phase1 compatibility snapshots)
- `s3://<OpsBucket>/evaluation/run_id=<id>/*.csv`

## 5. Step Functions split for 20-minute daily workload

### Why split

- Lambda max runtime is 15 minutes.
- Current daily runtime is ~20 minutes on local machine.
- A single Lambda daily job is not safe.

### Split strategy

- Split by ticker shards, not by feature type.
- Keep each shard under ~6-8 minutes to leave retry headroom.
- Start with 8 shards for 62 tickers (about 8 tickers/shard average).

When using SQS mode, replace shard concept with job chunks:

- `tickers_per_job = 100` (configurable)
- queue one message per job
- run worker in strict single concurrency (`ReservedConcurrentExecutions=1`)

### State machine behavior

1. `PrepareUniverse`

- Read monitor list and optional sector pool
- Write one manifest JSON to S3
- Return shard list

2. `FetchByShard` (Map)

- Each iterator handles one shard
- Fetch OHLC + aux + features for that shard
- Retries with exponential backoff on API errors

3. `GenerateSignals`

- Load current state
- Evaluate buy/sell actions
- Write daily signals to S3

4. `BuildReport`

- Build markdown report and compact JSON summary
- Write both to S3

5. `PersistAndNotify`

- Persist state/trades to DynamoDB
- Publish SNS message with summary + S3 links

### Does codebase need further split?

Yes, but phased:

- Phase1 (done in this change set):
  - remove hard path coupling
  - support local/aws config switch
  - make path handling backend-aware (local vs s3 URI tolerant)
- Phase2 (required for production AWS run):
  - introduce `StorageAdapter` for local_fs/s3 IO
  - introduce `StateRepository` for json/dynamodb
  - extract ticker-shard fetch callable from current monolithic daily workflow
- Phase3:
  - optimize shard size dynamically from previous run duration
  - add idempotency keys and partial rerun support

## 6. Config strategy

- `config.local.json`: local filesystem + json state
- `config.aws.json`: s3 paths + dynamodb state (target)
- Runtime switch via env var:
  - `JSA_CONFIG_FILE=config.local.json`
  - `JSA_CONFIG_FILE=config.aws.json`
  - `JSA_CONFIG_FILE=config.aws-sim.json` (phase1 local-AWS dual-run smoke)

  No-SFN job split parameters (Lambda env / schedule input):
  - `tickers_per_job` default 100
  - `recompute_features` and `fix_gaps` optional flags

## 7. CI/CD (recommended)

- GitHub Actions with OIDC role assumption.
- Branch policy:
  - `main` -> deploy to current production stack (single-project mode)
- Pipeline stages:
  1. unit tests
  2. package SAM
  3. deploy stack with parameter overrides

Implementation guide: `docs/GITHUB_AWS_CICD_SETUP.md`

## 8. Monthly cost estimate (rough)

Assumptions:

- 1 scheduled run per business day, ~22 runs/month
- no Step Functions; SQS mode with ~3 fetch jobs/day (290 tickers, 100/job)
- Lambda memory 2048 MB for data steps
- S3 storage 10-30 GB total
- DynamoDB on-demand with low R/W volume
- SNS email notifications ~1-3/day

Estimated range (USD/month):

- Lambda compute + requests: $1.5 - $6
- SQS + request cost: < $0.2
- S3 storage + requests: $0.5 - $3
- DynamoDB on-demand: $0.5 - $4
- EventBridge Scheduler: < $0.1
- SNS notifications: < $0.1

Total typical: **$3 - $14 / month**

Cost risks:

- If you place Lambdas in a private subnet with NAT gateway, NAT can dominate cost.
- Keep Lambdas outside VPC unless you really need private resources.

## 9. Operational checklist

- Enable CloudWatch alarms for failed executions and high duration.
- Enable S3 versioning on Ops bucket.
- Use KMS encryption for S3 and DynamoDB where needed.
- Keep J-Quants API key in Lambda environment variable (`JQUANTS_API_KEY`).
- Add run metadata table for observability (`run_id`, status, duration, error).

## 10. New code paths added for no-SFN mode

- `src/aws/job_splitter.py`: split tickers into fixed-size jobs
- `src/aws/handlers/dispatch_fetch_jobs.py`: dispatcher lambda (read list, split, enqueue)
- `src/aws/handlers/fetch_worker.py`: worker lambda (consume SQS, run ETL)
- `infra/sam/template-sqs.yaml`: no-StepFunctions infrastructure template

Current dispatcher scope:

- `DispatchFetchJobsLambda` currently targets production daily fetch fan-out.
- It does not orchestrate `universe` or `evaluation` pipelines yet.
- `universe` and `evaluation` can be added later as separate dispatcher/queue pairs when needed.

## 11. Confirmed no-SFN schedule (user-approved)

Design confirmation:

- This schedule is valid and practical without Step Functions.
- Re-dispatch at 18:30 gives one controlled retry window.
- Hard stop at 19:00 prevents endless retries and keeps operations predictable.
- 20:00 gated execution cleanly separates "data readiness" and "trading logic".

Sizing note for current workload (~290 daily tickers):

- `tickers_per_job=100` gives ~3 jobs per dispatch.
- This fits your measured runtime profile and keeps each job within Lambda 15-minute budget.
- Keep processing strictly serial (no concurrency) to respect 60 req/min API pacing.

Daily timeline (JST):

1. 18:00 trigger dispatcher

- Run `DispatchFetchJobsLambda`
- Split monitor list into jobs (`tickers_per_job=100`)
- Enqueue all fetch jobs to SQS

2. 18:30 trigger validation function

- Validate whether all tickers have latest data for today
- If false: trigger dispatcher again (second fan-out)

3. 19:00 trigger validation function again

- Validate latest data completeness for today
- If false: do NOT trigger dispatcher again
- Send failure notification email and persist `ready=false` for the day

4. 20:00 gate + run signal/report

- Read the propagated readiness flag
- If `ready=true`: run signal generation + report build + output persistence + success notification
- If `ready=false`: skip signal/report and only send/keep failure state

Recommended implementation detail for "pass false forward":

- Store daily readiness state in S3 ops bucket:
  - `s3://<OpsBucket>/run_status/date=YYYY-MM-DD/readiness.json`
  - payload example: `{ "ready": false, "validated_at": "...", "reason": "missing_latest_data" }`

UTC schedule mapping for EventBridge Scheduler:

- 18:00 JST -> 09:00 UTC
- 18:30 JST -> 09:30 UTC
- 19:00 JST -> 10:00 UTC
- 20:00 JST -> 11:00 UTC
