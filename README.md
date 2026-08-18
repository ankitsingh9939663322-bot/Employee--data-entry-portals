# Nexora Data Solutions — Employee Training Portal

A deployable Flask + PostgreSQL application for a **fictional, simulated data-entry
training environment**.

## Included

- Central employee accounts stored in PostgreSQL/SQLite.
- Employee-created DOB + password account.
- Passwords stored as secure hashes, never plaintext.
- New deterministic set of 200 simulated records each calendar day.
- Employee sees task progress only; no score/right/wrong count.
- Founder/Admin dashboard supports month-by-month historical performance.
- Monthly totals aggregate every saved daily result in the selected month.
- Monthly displayed accuracy is constrained to the configured 80–90% range; raw daily results remain stored.
- Historical daily results remain in PostgreSQL/SQLite and are not deleted on logout or browser close.
- Founder can select any month and open employee-level monthly details/history.
- CSRF protection and secure session-cookie settings.
- Gunicorn production server.
- Dockerfile.
- Render deployment configuration with managed PostgreSQL.
- Railway-compatible Docker deployment configuration.
- `/health` health-check endpoint.

## Fastest production deployment: Render

Render supports deploying Flask web services with Gunicorn, and its managed Postgres
can be attached to the service. See the official Render Flask deployment docs:
https://render.com/docs/deploy-flask

1. Put this folder in a private GitHub repository.
2. In Render, choose **New → Blueprint** and connect the repository.
3. Render reads `render.yaml` and provisions the web service + PostgreSQL.
4. Set the `FOUNDER_PASSWORD` secret in the Render dashboard to a strong password.
5. Deploy and open the generated HTTPS URL.
6. Optional: connect your own domain in Render.

Do not use a free database for an actual business workload; Render documents
limitations/expiry for free Postgres instances.

## Railway alternative

Railway can provision PostgreSQL and expose `DATABASE_URL` to the application.
Deploy this repository/Dockerfile, add PostgreSQL, set `DATABASE_URL` from the
Postgres service, set `SECRET_KEY` and `FOUNDER_PASSWORD`, then generate a public
domain.

## Required production settings

- Use a strong unique `SECRET_KEY`.
- Set a strong private `FOUNDER_PASSWORD`.
- Use PostgreSQL rather than SQLite for multi-user production.
- Keep the repository private.
- Enable HTTPS and `COOKIE_SECURE=1`.
- Back up the database.
- Add your own privacy/retention policy before collecting real employee data.
- For a real organization, add employee ID/email login, MFA, password recovery,
  account lockout/rate limiting, audit logs, and role management.

## Important

The company name, organization, employees, and data in this project are fictional.
This must not be represented as an existing company, government portal, bank, or
other real organization's system.


## Production environment variables

Set these in your hosting platform (Render/Railway), not in GitHub:

- `SECRET_KEY` — long random secret
- `FOUNDER_PASSWORD` — founder login password
- `FOUNDER_DOB` — founder login date of birth in `YYYY-MM-DD`
- `DATABASE_URL` — persistent PostgreSQL connection string
- `COOKIE_SECURE=1` — recommended when deployed over HTTPS
