# secrets/

**This directory is empty on purpose, and nothing in it is ever committed.**
It holds no keys, no tokens and no credentials — only this file, which is the
single exception to the ignore rule in `.gitignore`:

```
secrets/*
!secrets/README.md
```

It exists so that a place for local-only files is present and already ignored,
rather than being created in a hurry next to tracked code.

## Where the application actually reads your API key from

**Put `.env` in the PROJECT ROOT, beside `README.md` — not in this directory.**

`metascreener/main.py` resolves the env file as `project_root / ".env"`, so a
`.env` placed here is silently ignored: the application will prompt for a key
as though you had never written one, and nothing will say why. Copy
`.env.example` from the project root and edit it in place.

*(This file previously told users to put `.env` here, which is the instruction
F-129 records as failing. Corrected at wave 17f.)*

## What may go here

Local-only files you want kept out of git — an OAuth token, a
`credentials.json`, a private key. They are ignored automatically by the rule
above; you do not need to add anything to `.gitignore`.

Anything committed must be a template with no real values, such as
`credentials.SAMPLE.json`. The project's own key template is `.env.example` in
the project root.
