---
title: 'ADR-0023: Commercial lines .NET apps stay on Azure App Service'
doc_type: adr
owner_team: commercial-lines-dotnet
classification: Internal
system: Azure App Service
last_reviewed: 2025-11-05
access_groups:
- lm-eng-all
---

# ADR-0023: Commercial lines .NET apps stay on Azure App Service

**Status:** Accepted · **Date:** 2025-07-04 · **Deciders:** Chief Architect, Domain architect, Principal engineer

## Context

The .NET commercial lines apps run on App Service and integrate with Microsoft 365. Moving them to EKS was estimated at 14 engineer-months.

## Decision

Keep commercial lines apps on Azure App Service through 2027. Containerise only when an app needs a feature App Service lacks.

## Alternatives considered

- Move to EKS: rejected.
- Move to Azure Container Apps: rejected.

## Consequences

- Azure remains a production cloud with its own on-call rota.
- Deploys use GitHub Actions with Entra workload identity federation.
