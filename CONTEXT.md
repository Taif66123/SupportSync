# SupportSync

A small customer support application where a Customer creates a support Ticket and communicates with a Support Agent in real time.

## Language

**User**:
Any authenticated account, regardless of role.
_Avoid_: Account (reserved for the login concept), member

**Customer**:
A User who creates Tickets and communicates with support. Customers self-register.
_Avoid_: Client, end-user

**Support Agent**:
A User who receives Tickets, communicates with Customers, and resolves their issues. Created by an Admin only.
_Avoid_: Agent (unqualified), staff, operator

**Admin**:
A User who manages Users and oversees the ticket queue, but is not a ticket handler. Created by an Admin only.
_Avoid_: Superuser

**Ticket**:
A unit of customer support work, created by a Customer, that progresses through a lifecycle until closed.
_Avoid_: Issue, case, request

**Ticket Lifecycle**:
The ordered statuses of a Ticket: `open`, `in_progress`, `resolved`, `closed`. A Support Agent moves a Ticket between `open` and `in_progress` and to `resolved`, and may reopen a `resolved` Ticket. A Customer may close their own Ticket from any non-closed status; Support Agents and Admins may also close Tickets. `closed` is terminal for everyone — a follow-up means a new Ticket.
_Avoid_: Workflow, state machine

**Priority**:
The urgency of a Ticket (`low`, `medium`, `high`). Chosen by the Customer at creation; changeable afterwards by Support Agents and Admins only.
_Avoid_: Severity, importance

**Queue**:
The set of Tickets that are `open` and unassigned, from which Support Agents claim Tickets.
_Avoid_: Pool, inbox
