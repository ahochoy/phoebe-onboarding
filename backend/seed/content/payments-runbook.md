# Payments Runbook

This runbook is for engineers on the Payments team at Larkspur Labs. It covers the payment pipeline that lets clinics collect copays and deposits from patients. Payments is a restricted area. Treat everything here as internal. The team channel is `#payments`, and the on-call alias is `payments-oncall`.

## System overview

### Architecture

Patient payments flow from the booking web app to the Payments API, then to our processor integration, and finally to the settlement service, which reconciles every transaction against the processor's daily report. Every request carries an idempotency key, and the API stores keys for 48 hours so that retries never double-charge a patient.

### Key services

- `payments-api`: accepts charge and refund requests.
- `processor-gateway`: talks to the external payment processor. We use a fictional processor called Meridian Pay in this document.
- `settlement-worker`: runs nightly at 02:00 Pacific and reconciles transactions.
- `ledger`: the append-only record of every money movement.

## Common alerts

### Elevated charge failures

If the charge failure rate exceeds 5% for ten minutes, check the Meridian Pay status page first. If the provider is degraded, enable the `payments.retry_queue` flag so that failed charges are queued for retry and patients see a pending message instead of an error. If the provider is healthy, look at the most recent deploy of `payments-api` and roll back if it is the cause.

### Settlement mismatch

The settlement worker raises a mismatch alert when its totals differ from the processor report by more than one cent. Do not edit the ledger by hand. Follow these steps:

1. Run `settlement-cli diff --date YYYY-MM-DD` to list the differing transactions.
2. Check whether the difference is a timing issue. Transactions near midnight UTC are the most common cause.
3. For true mismatches, open a ticket for the finance operations team with the transaction IDs.
4. Do not issue a manual refund without finance approval.

### Webhook backlog

If the webhook queue depth grows beyond 10,000 messages, scale `processor-gateway` to 8 replicas with the standard scaling command and watch the consumer lag. A backlog usually means the processor is delivering a burst of delayed events.

## Procedures

### Issuing a refund

Refunds are issued from the admin console by a member of the support team. Engineers should only issue a refund through the API in an incident, with approval from the Payments lead. Always include the original charge ID and a reason code.

### Rotating processor credentials

Credentials rotate every 90 days. The process is documented in the secrets manager. Rotate the sandbox credentials first, verify a test charge, and then rotate production during a low-traffic window, which is typically Sunday morning Pacific.

## Compliance notes

We never store full card numbers. All card data is handled by the processor, and we store only tokens and the last four digits. Logs must never contain card data or patient names. Quarterly access reviews are run by the Payments lead, and any engineer who no longer needs access will have it removed.

## Escalation

Primary: the Payments on-call engineer. Secondary: the Payments lead. For suspected fraud or data exposure, also page the security on-call and follow the IT and Security Policy.
