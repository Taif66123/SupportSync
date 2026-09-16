# Users are deactivated, never deleted

Admins deactivate users (`is_active = false`) instead of deleting them, and tickets are never deleted. Deleting a user would orphan ticket history (every Ticket references its Customer and Support Agent), so identity records are permanent and access is revoked instead.
