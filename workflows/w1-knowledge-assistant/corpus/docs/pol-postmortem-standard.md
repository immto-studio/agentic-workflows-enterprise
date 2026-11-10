---
title: Postmortem standard
doc_type: policy
owner_team: sre-core
classification: Internal
system: ServiceNow
last_reviewed: 2026-04-08
access_groups:
- lm-eng-all
---

# Postmortem standard

- Every Sev1 and Sev2 incident has a blameless postmortem. There are no exceptions; an incident
  cannot be closed in ServiceNow until the postmortem link is attached.
- The draft is due within **5 business days** of resolution and is reviewed at the weekly
  reliability review (Wednesdays, 11:00 ET).
- Action items are Jira tickets with an owner and a due date; Sev1 actions are due within 30 days.
