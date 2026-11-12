# AutoLedger Workflow Status

This document describes current verified local flows and marks remaining work.
The configured local app uses the migrated `autoledger_dev_clone`; the original
`autoledger_db` has not been changed.

## Current vehicle-history workflow

1. The existing Admin account is initialized once through the bootstrap
   screen; passwords are hashed by the backend.
2. Authenticated users with vehicle-read access search and filter the shared
   vehicle registry.
3. Vehicle details expose current ownership and associated service, repair,
   mileage, inspection, document, and verification history.
4. Super Admin alone creates/corrects vehicle identity and shared history.
   Ownership transfer uses the existing atomic database function.
5. Backend validation and PostgreSQL constraints/triggers protect duplicate
   identity values, ownership, mileage, and audit history.
6. Authorized users can use the existing vehicle CSV and history PDF outputs.

## Proposed dealership purchase workflow

1. Select an active membership from the header business selector; the UI
   sends its ID with each commerce API request.
2. Select a business supplier and vehicle identity, or submit an unknown VIN
   to Super Admin review (review request not implemented).
3. Create a purchase header and one or more vehicle price/condition lines.
4. Validate and commit the purchase atomically.
5. On receipt, create/update that business's inventory state.
6. Add optional initial payment; calculate paid amount and balance from
   completed payment events.

The application and integration tests implement these transactions on the
migrated development clone. Commerce routes resolve the selected active
membership and scope business data to it. Do not infer this makes the
unmigrated `autoledger_db` commerce-ready.

## Proposed dealership sales workflow

1. Select a vehicle in the active business's available inventory.
2. Select a customer and enter the sale date, price, discount, and optional
   partial/full payment.
3. Lock inventory rows in vehicle-ID order and recheck availability.
4. Create the sale and its line items in one transaction; reserve/complete
   inventory and record payment before commit.
5. Reject a duplicate/concurrent sale after the first transaction changes
   stock state.
6. Later payment events update calculated balances; PDFs/reporting are
   available only when the related schema exists.

Tests for this flow, duplicate sale prevention, and rollback pass on the
isolated migrated test clone. This does not make the feature live in
`autoledger_db`.

## Multi-business workflow (partially implemented)

1. Authenticate a user and list active business memberships.
2. User selects a business; backend validates the membership and uses the
   role assigned to that membership.
3. Commerce customer/supplier, purchase/sale, inventory, payment, history,
   PDF, and financial-report endpoints filter by the selected business.
4. Vehicle identity and approved history remain shared/read-only for business
   users; only Super Admin mutates the shared registry.
5. On business switch, the backend revalidates membership and all subsequent
   operations use the newly selected business context.

Cross-business endpoint tests currently verify commerce list/detail/update,
history, inventory, payment, invoice/receipt, and financial-report isolation
on the development clone. Business creation/member administration,
tenant-aware legacy triggers and business audit access, plus browser-level
business switching tests remain. Do not deploy as a shared multi-tenant
application until those are complete and independently verified.

## Payment and audit rules

- Payment balances should be derived from settled payment/refund events;
  pending, failed, and voided events do not reduce the balance.
- Reversals must preserve posted financial history rather than deleting it.
- Audit entries should include authenticated actor, business context, action,
  entity, and timestamp. Existing global audit history is not business
  scoped; it is Super Admin-only until scoped APIs are implemented.
