# Evercrest Health — Streamlit deployment

Deploys the **practitioner EHR frontend** (the self-contained chart in
`domains/healthcare/ehr_data.py` + `ehr_theme.py`, wired through `app.py`) to
Streamlit Community Cloud, pointed at the Evercrest Galileo project, backed by
OpenAI + PostgreSQL/pgvector.

The app is driven entirely by secrets — no code fork per tenant:
`default_domain`, `galileo_project`, and `galileo_log_stream` all come from the
deploy secrets (see `setup_env.py`). `default_domain = "healthcare"` makes `/`
open on the Evercrest EHR.

## Deployment coordinates

- Repository: `Galileo-Agent-Labs/galileo-golden-demo`
- Branch: `evercrest-ehr-frontend` (this branch)
- Entrypoint: `app.py`
- Python: `3.12`
- Suggested URL: `evercrest-demo.streamlit.app`

## Secrets — the golden rule

**Never commit real keys.** The Galileo API key lives in 1Password (item
`EHR Assistant`); OpenAI and Postgres are separate items. Two supported paths:

- **Streamlit Cloud:** paste `.streamlit/secrets.evercrest.toml.template` (filled
  in) into the app's **Settings → Secrets**.
- **Local / installer:** resolve from 1Password into a private `.env`:
  ```bash
  op inject -i config/evercrest/evercrest.env.op.example -o .env
  ```
  (`config/evercrest/evercrest.env.example` is the same shape without 1Password.)

Traces land in the Galileo project **`EHR Assistant`**, log stream
**`chart-agent`** (set via `galileo_project` / `galileo_log_stream` in secrets).

## 1. Provision PostgreSQL

A network-reachable PostgreSQL with the `vector` extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Use TLS (`sslmode=require`). If the provider offers direct + pooled URLs, use the
direct URL to initialise and the pooled URL in Streamlit.

## 2. Initialise the healthcare data

Create a local `.streamlit/secrets.toml` from the template with the **direct**
`postgres_url`, then:

```bash
python helpers/setup_vectordb.py healthcare
```

This loads the healthcare patient/medication/history tables and the RAG index.
It is destructive only to the healthcare collection it manages.

> Note: the EHR **chart** itself renders from bundled data with no database, so
> the UI comes up even before this step. The database powers the copilot's
> retrieval + tool calls.

## 3. Create the Streamlit app

In Streamlit Community Cloud, create an app with the coordinates above, select
Python 3.12, and paste the filled-in secrets into **Advanced settings → Secrets**
(swap the direct DB URL for the pooled one before saving).

Do not upload a localhost URL and do not commit `.streamlit/secrets.toml`.

## 4. Verify

1. `/` opens the Evercrest Health EHR (patient banner, vitals flowsheet, labs).
2. The patient selector is populated (P001–P030).
3. Open **Clinical Assistant**, ask a medication question → grounded response.
4. The trace appears in the `EHR Assistant` Galileo project / `chart-agent`
   log stream.
