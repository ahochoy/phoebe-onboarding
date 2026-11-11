# Engineering Practices

This page describes how engineers at Larkspur Labs build and ship software. It applies to every engineering team, including Platform and Payments. Individual teams add their own conventions on top. If a practice here no longer serves us, open a pull request against this document, as we do for code.

## Our approach

### Principles

We favor small changes, fast feedback, and boring technology. A good change is easy to review, easy to revert, and easy to explain. We would rather ship ten small pull requests than one large one, and we rely on automated checks to keep quality high.

### Stack overview

Most services are written in Go and Python and run on Kubernetes. Our web apps use TypeScript and React. We use PostgreSQL as the primary datastore and Redis for caching and queues. Infrastructure is defined in Terraform and lives in the `infra` repository. You do not need to know all of this on day one. Your buddy will walk you through the parts that matter for your team.

## Code review

### Opening a pull request

Keep pull requests under roughly 400 changed lines where you can. Write a description that explains why the change exists, not only what it does. Link the ticket, add a test plan, and include screenshots for anything a user can see. Mark work in progress as a draft.

### Reviewing

Every change needs one approving review from a teammate who is not the author. We aim to give a first response within one business day. Reviewers focus on correctness, clarity, and risk. Style questions are handled by the formatter and linter, not by humans. Prefix optional suggestions with "nit:" so authors know what is blocking. Be kind, and assume good intent.

### Merging

Squash and merge once checks pass and you have an approval. You own your change after it merges, so watch the deploy and be reachable for a while afterwards.

## Testing

### What we expect

New behavior comes with tests. Bug fixes come with a test that fails before the fix. Unit tests should run in seconds. Integration tests cover the boundaries between services, and we keep a small set of end-to-end tests for the most important flows, such as booking an appointment.

### Flaky tests

A flaky test is a bug. If a test fails intermittently, quarantine it with the `flaky` label, file a ticket, and fix it within the sprint. Do not simply rerun the pipeline and move on.

## Deploying

### Continuous delivery

Every merge to `main` is deployed automatically to staging and, after a short canary period, to production. We deploy many times a day. There is no deploy freeze except for the winter break and during active incidents.

### Feature flags

Risky or incomplete work goes behind a feature flag. Flags are removed within 30 days of full rollout, and the author of the flag is responsible for cleaning it up.

### Rollbacks

If a deploy causes problems, roll back first and investigate second. The rollback command is documented in the runbook for each service, and anyone on the team is allowed to use it.

## Design docs and decisions

Changes that affect more than one team, add a new service, or are hard to reverse start with a short design doc. Keep it to two pages: the problem, the options you considered, and your recommendation. Share it in the `#eng-design` channel for at least three business days before building. We record final decisions in short architecture decision records, stored beside the code.

## Working agreements

### Communication

Default to asynchronous communication. Write in public channels so that others can learn from the discussion. Meetings should have an agenda and produce notes. Our engineering all-hands happens on the first Thursday of the month.

### Estimating and planning

Teams plan in two-week sprints. We estimate loosely, in small, medium, and large, and we care more about the flow of work than hitting exact dates. Planning is on Mondays, and retrospectives are every second Friday.

### Learning and growth

Every engineer has a learning stipend, and we encourage pairing, brown-bag talks, and rotating through on-call. Your manager will set growth goals with you during your first month. You are never expected to know everything. Asking a question early is always better than staying stuck.

## Security and privacy basics

Never commit secrets. Use the secrets manager, and rotate anything that leaks. Treat customer data as restricted, and use only synthetic data in development and tests. Read the IT and Security Policy for the full rules.
