# Deployment checklist

- [ ] Create private GitHub repository.
- [ ] Deploy with Render Blueprint or Docker/Railway.
- [ ] Provision PostgreSQL.
- [ ] Set a strong FOUNDER_PASSWORD secret.
- [ ] Confirm SECRET_KEY is generated/unique.
- [ ] Confirm COOKIE_SECURE=1.
- [ ] Open /health and verify `status: ok`.
- [ ] Create a test employee account.
- [ ] Complete 2–3 test entries from another browser/device.
- [ ] Verify founder dashboard receives the test result.
- [ ] Verify employee does not see correct/wrong/accuracy.
- [ ] Configure database backups.
- [ ] Add custom domain if desired.
- [ ] Before real use, review privacy, retention, access-control and employee-consent requirements.

- [ ] Select a prior month in Founder dashboard and confirm historical totals remain visible.
- [ ] Log out, close the browser, log back in, and confirm saved daily progress/history remains.
- [ ] Verify a month with actual accuracy below 80% displays monthly accuracy within 80–90%.
- [ ] Verify a month with actual accuracy above 90% displays monthly accuracy within 80–90%.
- [ ] Verify each month is calculated independently and old months are not overwritten.

- [ ] Set `FOUNDER_DOB` in the hosting platform as `YYYY-MM-DD` (do not commit it to GitHub).
