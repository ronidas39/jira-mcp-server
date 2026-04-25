# Runbook: set up Jira credentials

## When to use this

Initial setup of a new environment, or rotation of an expired API token.

## API token mode (default)

1. Sign in to https://id.atlassian.com/manage-profile/security/api-tokens.
2. Click **Create API token** and label it (for example `jira-mcp-server`).
3. Copy the generated token. You will not see it again.
4. In your local checkout, copy `.env.example` to `.env` if you have not already.
5. Set the following:

   ```
   JIRA_BASE_URL=https://your-domain.atlassian.net
   JIRA_AUTH_MODE=api_token
   JIRA_EMAIL=your-email@example.com
   JIRA_API_TOKEN=<paste here>
   ```

6. Restart the server:

   ```bash
   python -m jira_mcp
   ```

7. Watch the startup log; you should see:

   ```
   {"event": "jira.connectivity.ok", "base_url": "https://..."}
   ```

## OAuth mode

1. Create an OAuth 2.0 (3LO) app at https://developer.atlassian.com/console/myapps/.
2. Configure the callback URL to match `JIRA_OAUTH_REDIRECT_URI`.
3. Add the scopes `read:jira-work`, `write:jira-work`, `read:jira-user`, and `offline_access`.
4. Copy the client id and secret into `.env`:

   ```
   JIRA_AUTH_MODE=oauth
   JIRA_OAUTH_CLIENT_ID=...
   JIRA_OAUTH_CLIENT_SECRET=...
   JIRA_OAUTH_REDIRECT_URI=...
   ```

5. Run `python -m jira_mcp.scripts.oauth_login` to perform the initial 3LO flow once that script lands in M1.

## Rotation cadence

- API tokens: rotate every ninety days, or immediately if leaked.
- OAuth refresh tokens: managed automatically; revoke from Atlassian profile settings if needed.

## Troubleshooting

| Symptom                                | Likely cause                  | Fix                                                                |
| -------------------------------------- | ----------------------------- | ------------------------------------------------------------------ |
| `401 Unauthorized` at startup          | Bad token or wrong email      | Regenerate the token; double-check the email tied to the token     |
| `403 Forbidden` on writes              | Project permissions           | Make sure the user has the right project role                      |
| Stream of `429` responses              | Rate-limited                  | Wait; lower `JIRA_MAX_CONCURRENCY` if it persists                  |
| `SSL: CERTIFICATE_VERIFY_FAILED`       | Corp proxy with custom CA     | Set `SSL_CERT_FILE` to the corporate CA bundle                     |
