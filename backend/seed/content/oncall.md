# On-call Guide

Engineers at Larkspur Labs take turns carrying the pager for the services their team owns. This guide explains what on-call means, what we expect, and how we look after each other. You will not be on call during your first month. You will shadow a teammate first.

## How on-call works

### Rotations

Each team runs a weekly rotation that changes hands on Monday at 10:00 Pacific. There is a primary and a secondary. The primary responds first, and the secondary steps in if the primary does not acknowledge a page within ten minutes. Rotations are managed in the on-call tool, and you can swap shifts with teammates at any time. Please tell your manager and update the tool.

### Joining the rotation

New engineers shadow for one full week and then join the rotation as secondary. After one rotation as secondary, you become eligible to be primary. Your buddy and manager will confirm when you are ready. Nobody is pushed into the pager before they feel prepared.

### Expectations

When you are primary, you should be near a laptop with a working internet connection and able to acknowledge a page within ten minutes. You do not need to stay at your desk, and you can still go to dinner or walk the dog. If you cannot keep this commitment on a given day, swap with the secondary ahead of time.

## Severity levels

### Sev1: critical

Customers cannot book appointments, data is at risk, or the whole product is down. Page the on-call right away, open an incident channel named `#inc-YYYYMMDD-short-name`, and appoint an incident lead. Post status updates at least every 30 minutes.

### Sev2: major

A significant feature is degraded or a subset of customers is affected. Respond within 30 minutes. Open an incident channel if the work will take more than an hour.

### Sev3: minor

A small bug or a problem with a workaround. File a ticket and handle it during working hours. Sev3 issues should not wake anybody up.

## Handling a page

### First ten minutes

1. Acknowledge the page so that others know you are on it.
2. Open the service dashboard and read the alert description and linked runbook.
3. Decide on a severity and, for Sev1 or Sev2, announce it in `#incidents`.
4. Mitigate first. Roll back a recent deploy or disable a feature flag if it looks related.
5. Ask for help early. Escalating is not failing, and the secondary is there for exactly this.

### Communication during incidents

Keep one person in charge, called the incident lead. The lead coordinates and communicates, and other people investigate. Write what you are doing in the incident channel so that anyone can catch up. Do not guess in public about root causes. Share facts and hypotheses clearly labeled as such.

### Customer communication

Support owns messages to customers. Give them a plain-language summary and an expected time for the next update. Never share customer data in the channel.

## After the incident

### Blameless review

For every Sev1 and Sev2 we hold a blameless review within five business days. We write a timeline, find contributing factors, and agree on follow-up actions with owners and dates. The goal is to learn and make the system safer. The goal is never to blame an individual.

### Follow-up work

Action items go into the team backlog with the `incident-followup` label. Teams review open follow-ups at every sprint planning.

## Looking after yourself

### Compensation and time off

On-call weeks earn a flat stipend of $400 for the primary and $150 for the secondary. If you are paged overnight and lose significant sleep, take the following morning off, with no PTO deducted. Tell your manager and mark it in the tool.

### Reducing noise

A noisy alert is a bug. If a page was not actionable, add a ticket to fix, tune, or delete the alert. We review alert quality at the end of every rotation, and we aim for fewer than two pages per on-call shift outside business hours.

### Useful links

The runbooks live in the `runbooks` repository, with a folder for each service. The status page is edited from the on-call tool. Questions about on-call go to `#oncall` in Slack.
