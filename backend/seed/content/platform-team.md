# Platform Team Breakdown

Welcome to Platform. We are the team that builds and runs the foundations the rest of Larkspur Labs builds on: the deploy pipeline, the Kubernetes clusters, the shared service libraries, observability, and the internal developer portal. Our customers are our fellow engineers, so a good day for us is a day when nobody has to think about infrastructure. Our Slack channel is `#platform`, and our team email is platform@larkspur-labs.example.

## The team

### Who is who

Jordan Lee is the engineering manager for Platform and your manager. Jordan runs our weekly planning, handles career conversations, and is the right person for anything about priorities or time off. Jordan's one-on-ones are on Tuesday afternoons.

Mei Tanaka is a senior engineer and your onboarding buddy. Mei has been at Larkspur for four years and knows the history of most of our systems. She will pair with you during your first weeks and answer the questions that feel too small to ask anyone else.

Dmitri Volkov is a staff engineer and our technical lead. Dmitri owns the architecture of the deploy pipeline and reviews most cross-team design docs. He is based in Chicago and keeps Central time hours.

Anika Rao is an engineer focused on observability. She owns our dashboards, alerting, and the tracing setup, and she runs the monthly alert-quality review.

Tomas Silva is a site reliability engineer who looks after the Kubernetes clusters, cost, and capacity. Tomas is also the person to ask about cloud access and sandbox environments.

### Where we work

Mei, Anika, and Jordan are based in Portland. Dmitri and Tomas are in Chicago. We are a hybrid team, so on any given day, some of us are at the office and some are at home. Our team room in Portland is called the Greenhouse. Nobody is expected to be in the office on any particular day, but many of us gather on Wednesdays.

## What we own

### Services and systems

Platform owns the following systems. You will hear these names a lot.

- **Beacon**, the deploy pipeline, which takes a merged change to staging and production.
- **Trellis**, our Kubernetes platform, including cluster upgrades and ingress.
- **Lantern**, observability: metrics, logs, traces, and alerting.
- **Atlas**, the internal developer portal, where teams find services, owners, and runbooks.
- **Kit**, the shared service libraries for Go and Python.

### What we do not own

We do not own product services such as scheduling or reminders. Those belong to the product teams. If you are not sure who owns something, check Atlas, or ask in `#platform`.

## How we work

### Rhythm of the week

Monday: sprint planning at 10:30 Pacific. Tuesday: Jordan's one-on-ones. Wednesday: team lunch at the Portland office, and an optional video call for the remote folks. Thursday: design review hour. Friday: demos and, every second Friday, a retrospective.

### Standups

We have a short asynchronous standup in `#platform` each morning. Post what you did, what you plan to do, and whether you are blocked. There is no daily meeting. If you are blocked, say so right away and tag somebody.

### Requests from other teams

Other teams file requests through the Platform intake form. A rotating triage engineer reads the queue each morning and responds within one business day. Urgent issues go to the on-call engineer. In your first month you will not take triage duty, but you are welcome to watch how it works.

## Your first weeks

You will start with small, well-scoped tasks in Kit and Atlas so that you can learn the codebase and deploy a change on your own within the first week. Mei will help you pick them. By the end of your first month, we hope that you will have shipped several changes and started shadowing on-call. See the First-Week Schedule for details of your first five days.

## Ways to get help

Ask in `#platform` for anything technical. Ask Mei for the unwritten rules. Ask Jordan for anything about priorities, growth, or how you are doing. If you are ever unsure whether a question is too basic, please ask it. We all remember being new.
