# Spend-limit mode: degrade before AWS stops the database

Plan 5, item 1. Status: draft for owner approval.

## Intent

The AWS project has a $30/month spend limit, shared with another portfolio
project. When the limit is reached, AWS stops Aurora
(`StopDBCluster` by `AWSServiceRoleForBudgetsSpendLimitMember`, seen
2026-11-17 07:07 UTC on staging). Today that shows visitors a 500, fails
deploys at `ops migrate` with a raw AWS error, and tells nobody.

The owner wants:

1. **Approaching the limit:** a degraded experience. Visitors still browse
   tasks, documents and the admin views; anything that spends (chat, uploads
   and links that need embedding) is disabled, with a banner saying features
   are limited because of spend restrictions.
2. **Limit reached, database stopped:** an unavailable screen, and an email to
   the owner.
3. **Nothing spends automatically.** The owner restarts by hand with one simple
   command once the limit allows it.

## Goals

- Phoebe pauses itself early enough that AWS's stop is a rare backstop.
- A stopped database shows a clear offline screen, never a 500.
- The owner is emailed both when the pause trips and when the database stops.
- One command brings an environment back: start the cluster, wait, reopen.
- Deploys against a stopped database stop early with that command in the message.

## Non-goals

- A read-only copy of the data for a hard stop (S3 snapshot). Rejected by the
  owner: a hard stop shows the offline screen.
- Automatic restart, or a CodePipeline restart button.
- Per-project cost attribution. The budget stays account-wide on purpose: the
  other project's spend counts against the same limit.

## Anti-goals

- Anything that starts the cluster or reopens chat without the owner.
- An email address in the repository or passed through Claude: the owner
  provides it at apply time.

## Approaches

1. **Pause first, AWS stop as the backstop (chosen).** Our account-wide budget
   trips the existing `chat_paused` state well below the spend limit; a hard
   stop closes the demo and shows the offline screen; one command restores.
2. Approach 1 plus a read-only seed snapshot during a hard stop. Rejected:
   every read path needs a second source, for a case approach 1 makes rare.
3. A CodePipeline "Restart" button. Rejected as overkill against a one-line
   command.

## Design

**Budget (infra/bootstrap, owner-applied).** `monthly_budget_usd` goes from 20
to 30 (the spend limit). The existing per-env budgets notify their SNS topics
at **70% of actual spend ($21)**, leaving $9 for the several hours AWS cost
data lags. The same notification also emails the owner
(`subscriber_email_addresses`, from a new `alert_email` variable the owner
passes as `TF_VAR_alert_email` at apply time; never committed).

**Soft pause (exists).** The budget Lambda sets `chat_paused`. In that state
chat, search, uploads and links are refused; tasks, documents, the viewer and
admin keep working. The database keeps running and idles near $0 at 0 ACU.

**Banner (frontend).** For the `chat_paused` reason, replace the "Rate limit
exceeded" pill with a banner across the top of every page: "Chat and uploads
are paused to keep this demo within its spending limit. Everything else works
as usual." The per-session and global rate-limit reasons keep the pill.

**Hard stop: close and notify (infra/app).** An EventBridge rule in us-east-2
on the RDS event for this env's cluster stopping (`RDS-EVENT-0150`, DB cluster
stopped) targets:
- the budget Lambda, which sets `closed` (never downgrading an operator's
  `closed`; it already never sets `open`), so the landing page shows the
  existing offline copy and nothing reaches the database;
- an SNS topic `phoebe-alerts-<env>` with the owner's email subscription.
The rule matches stops from any source; a manual stop also closes the demo,
which is what a manual stop wants anyway.

**Stopped database in the API (backend).** `db_data_api.py` maps
`InvalidResourceStateException` to `DatabaseUnavailable("stopped")`. The API
returns 503 `database_stopped`; the frontend shows the offline screen for it
(not the "waking up" copy, since a stopped cluster never wakes by itself).
This covers the minutes before the EventBridge rule closes the demo.

**Restart (Makefile).** `make db-start ENV=staging|production`:
`aws rds start-db-cluster`, waits for `available` (`aws rds wait
db-cluster-available`), then sets the env's control state to `open` through
`python -m phoebe control open` with the DynamoDB backend. If the cluster is
already available it only reopens. AWS also restarts a stopped cluster by
itself after 7 days; the demo stays `closed` until the owner runs the command.

**Deploys (ci/deploy.sh).** Before `ops migrate`, read the cluster status. If
it is `stopped` or `stopping`, stop with: "database is stopped (spend limit?):
run make db-start ENV=<env>, then re-run". No automatic start.

## Left to the builder

- Exact banner styling (match the existing status pill and Larkspur tokens).
- The RDS event pattern details (source, detail-type, event id, cluster ARN).
- Whether `db-start` lives in the Makefile alone or a small `ci/db-start.sh`
  it calls (prefer the script, so `make deploy-check` can test it offline).
- Tests at each layer: Data API error mapping, the 503 code and its copy,
  banner versus pill per reason, the Lambda's event handling, the tftest for the
  rule and topic, and the offline test of the restart script.
