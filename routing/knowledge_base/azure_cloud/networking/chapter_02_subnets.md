---
topic: azure_cloud
subtopic: networking
chapter_id: chapter_02_subnets
document_id: az-net
version: 1.0
---

# Subnets
A VNet is divided into one or more subnets, each with its own CIDR range
carved out of the VNet's address space, for example 10.0.1.0/24. Azure
reserves five IP addresses in every subnet (network address, default
gateway, two for DNS, and the broadcast address). Subnets can each have
their own Network Security Group and route table attached.
