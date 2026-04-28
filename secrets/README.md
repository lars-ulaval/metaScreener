# secrets/
This folder is intentionally ignored by Git.

Put local-only sensitive files here, for example:
- .env (API keys)
- OAuth tokens
- credentials.json / token.json
- private keys

Commit only templates (no real values), such as:
- .env.example
- secrets/credentials.SAMPLE.json
