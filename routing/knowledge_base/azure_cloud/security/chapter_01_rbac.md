---
topic: azure_cloud
subtopic: security
chapter_id: chapter_01_rbac
document_id: az-sec
version: 1.0
---

# Role-Based Access Control (RBAC)
Azure RBAC assigns roles, such as Owner, Contributor, or Reader, to a
security principal at a specific scope: a management group, subscription,
resource group, or individual resource. Role assignments are additive -
there is no explicit "deny" assignment in standard RBAC, except through
Azure Policy or the separate deny-assignment mechanism used by Blueprints.
