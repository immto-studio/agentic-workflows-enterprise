---
title: Production change management
doc_type: policy
owner_team: it-service-management
classification: Internal
system: ServiceNow
last_reviewed: 2026-09-22
access_groups:
- lm-eng-all
---

# Production change management

- Standard changes (pre-approved templates) need no CAB. Normal changes are approved at the Change
  Advisory Board on **Thursdays at 14:00 ET**.
- Production deploys run through GitHub Actions environments named `production`, which require an
  approved ServiceNow change number and one reviewer from the owning team. Jenkins `deploy-prod`
  is retired for all services except the mainframe batch pipeline.
- The 2026 year-end freeze runs from **2026-12-14 to 2027-01-04**. Emergency changes need the
  incident commander and a director to approve in ServiceNow.
