# F016 — Session Persistence & Recovery

Status: in progress. The accepted seven-panel Windows layout is unchanged.

Session snapshots must be stored under per-user local application data, use an explicit versioned schema, be published atomically, and restore only selections whose local media identity is revalidated. F009 candidate review must remain separate from F014 final approval; F010 readiness and F015 READY-only export are never bypassed.

No credentials, provider response bodies, signed URL query parameters, media payloads, or exported footage may be stored in session snapshots.
