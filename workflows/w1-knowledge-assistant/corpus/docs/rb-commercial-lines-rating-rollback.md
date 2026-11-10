---
title: Rolling back commercial-lines-rating on Azure App Service
doc_type: runbook
owner_team: commercial-lines-dotnet
classification: Internal
system: Azure App Service
last_reviewed: 2026-08-05
access_groups:
- lm-eng-all
---

# Rolling back commercial-lines-rating on Azure App Service

`commercial-lines-rating` is a .NET 8 API on Azure App Service (`app-cl-rating-prod`, resource group
`rg-cl-rating-prod`, subscription `sub-commercial-lines-prod`). Deploys go to the `staging` slot
and are swapped into production by the GitHub Actions workflow `deploy-azure.yml`.

## Roll back

The previous release is still in the `staging` slot after a swap, so a rollback is another swap:

```
az account set --subscription sub-commercial-lines-prod
az webapp deployment slot swap --resource-group rg-cl-rating-prod --name app-cl-rating-prod \
  --slot staging --target-slot production
```

The swap takes about 90 seconds and warms up the instances before switching traffic.

## Check

- Application Insights `appi-cl-rating-prod`: `requests | where timestamp > ago(10m) | summarize count() by resultCode`
- Rating p95 should return below 800 ms within 5 minutes.

Do not redeploy from an older commit during an incident; the swap is faster and keeps configuration.
