# Azure VNet Flow Logs - Platform Update (April 2026, fictional for testing)

Virtual network flow logs replace the older NSG flow logs. Key differences
to be aware of when migrating:

- Flow logs are now attached to the **virtual network** scope, so one log
  covers all NICs and subnets in the VNet; you no longer need one log per
  network security group.
- Retention can be set from 1 to 365 days when the storage account is in
  the same region; cross-region storage caps retention at 90 days.
- Records are written in version 4 schema, which adds an `encryption`
  field showing whether the flow was carried over an encrypted path.
- Pricing is per gigabyte of logs collected; the first 5 GB per
  subscription per month are free.

Migration tip: run both log types in parallel for one billing cycle and
compare record counts before disabling the NSG flow logs. Traffic
Analytics dashboards accept either source, but mixing both double-counts
flows for the overlap period.
