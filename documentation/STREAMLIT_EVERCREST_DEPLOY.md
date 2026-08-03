# Evercrest Health — Streamlit deployment

> **Superseded:** Use
> [`EVERCREST_STREAMLIT_DEPLOYMENT_RUNBOOK.md`](EVERCREST_STREAMLIT_DEPLOYMENT_RUNBOOK.md)
> for current URLs, branch mappings, Cisco 1Password references, update,
> rotation, rollback, and verification procedures. This file is retained only
> for historical EHR v2 implementation context.

Deploys the **practitioner EHR frontend** (the self-contained chart in
`domains/healthcare/ehr_data.py` + `ehr_theme.py`, wired through `app.py`) to
Streamlit Community Cloud as **its own app**, pointed at the Evercrest Galileo
project, and **reusing the same Neon Postgres backend** as the existing
golden-demo deployment.

The app is driven entirely by secrets — no code fork per tenant:
`default_domain`, `galileo_project`, and `galileo_log_stream` all come from the
deploy secrets (see `setup_env.py`). `default_domain = "healthcare"` makes `/`
open on the Evercrest EHR.

## Deployment coordinates

- Repository: `Galileo-Agent-Labs/galileo-golden-demo`
- Branch: `evercrest-ehr-frontend` (this branch)
- Entrypoint: `app.py`
- Python: `3.12`
- URL: `evercrest-demo-v2.streamlit.app` (this is a **separate** app from
  the main golden-demo deployment; only the database is shared)

## Secrets — the golden rule

**Never commit real keys.** The Galileo API key lives in 1Password (item
`EHR Assistant`). Two supported paths:

- **Streamlit Cloud:** paste `.streamlit/secrets.evercrest.toml.template` (filled
  in) into the app's **Settings → Secrets**.
- **Local / installer:** resolve from 1Password into a private `.env`:
  ```bash
  op inject -i config/evercrest/evercrest.env.op.example -o .env
  ```
  (`config/evercrest/evercrest.env.example` is the same shape without 1Password.)

Traces land in the Galileo project **`EHR Assistant`**, log stream
**`chart-agent`** (set via `galileo_project` / `galileo_log_stream` in secrets).

## 1. Reuse the shared Neon Postgres — do NOT provision or re-seed

This app points at the **same** Neon database the main golden-demo deployment
already uses. The healthcare tables (`healthcare_patient/medication/history`)
and the hosted RAG index are already loaded there, so:

- **Do not** run `helpers/setup_vectordb.py` (that step is destructive and
  already done on the shared DB).
- **Do not** provision a new database.

Just supply the **same** `postgres_url` this app's `secrets` as the main app
uses. Get it from the existing deployment's **Streamlit Cloud → Settings →
Secrets** (or 1Password, if you keep it there). Use the **pooled** Neon URL for
the runtime, with `?sslmode=require`:

```toml
postgres_url = "postgresql://USER:PASSWORD@ep-xxx-pooler.<region>.aws.neon.tech/neondb?sslmode=require"
```

Because both apps use `domain = healthcare` with OpenAI embeddings, they resolve
to the same RAG index name, so this app reads the existing embeddings — no
rebuild needed. Both apps only **read** the healthcare data, so sharing is safe.

> The EHR **chart** renders from bundled data with no database at all; the shared
> Neon DB only powers the copilot's retrieval + tool calls.

## 2. Create the Streamlit app

In Streamlit Community Cloud, **New app → From existing repo**:

- Repository `Galileo-Agent-Labs/galileo-golden-demo`, branch
  `evercrest-ehr-frontend`, main file `app.py`, Python 3.12.
- Give it a distinct URL (e.g. `ehr-assistant`) so it doesn't collide with the
  main app.
- In **Advanced settings → Secrets**, paste the filled-in
  `.streamlit/secrets.evercrest.toml.template`: the `EHR Assistant` Galileo
  values **plus the same Neon `postgres_url`** from step 1.

Do not commit `.streamlit/secrets.toml`.

## 3. Verify

1. `/` opens the Evercrest Health EHR (patient banner, vitals flowsheet, labs).
2. The patient selector is populated (P001–P030) — served from bundled data.
3. Open **Clinical Assistant**, ask a medication question → grounded response
   (this confirms the shared Neon DB + RAG index are reachable).
4. The trace appears in the `EHR Assistant` Galileo project / `chart-agent`
   log stream.
