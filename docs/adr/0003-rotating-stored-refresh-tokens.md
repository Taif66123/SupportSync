# Short-lived access JWT + rotating stored refresh tokens

Auth issues a ~15-minute stateless access JWT and a ~7-day refresh token that is stored in a database table, rotated on every use, and revocable (logout, password change). The stateless alternative (no refresh-token storage) is simpler but cannot revoke a leaked session before expiry; we accept the extra table and rotation logic to get revocability, which is the pattern production systems need.
