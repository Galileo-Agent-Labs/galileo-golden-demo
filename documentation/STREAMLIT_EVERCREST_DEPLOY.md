# Evercrest Streamlit deployment

This branch is prepared for an OpenAI-backed Evercrest Health deployment on
Streamlit Community Cloud with PostgreSQL/pgvector as its only data backend.
It intentionally excludes local-model and document-ingestion dependencies from
the hosted runtime.

## Deployment coordinates

- Repository: `Galileo-Agent-Labs/galileo-golden-demo`
- Branch: `codex/evercrest-streamlit`
- Entrypoint: `app.py`
- Python: `3.12`
- Requested URL: `evercrest-demo.streamlit.app`

## 1. Provision PostgreSQL

Use a network-reachable PostgreSQL instance that supports the `vector`
extension. Run this once with an administrative connection:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Use TLS for the public connection. If the provider offers direct and pooled
URLs, use the direct URL while initializing and the pooled URL in Streamlit.

## 2. Initialize healthcare data

Create a temporary `.streamlit/secrets.toml` from the supplied template and set
the direct `postgres_url`, OpenAI key, and Galileo project/log-stream settings.
Then run:

```bash
python helpers/setup_vectordb.py healthcare
```

The command creates `healthcare_hosted_index` and loads the healthcare patient,
medication, and history tables. It is destructive only to the healthcare
collection/tables it manages, so do not point it at an unrelated database.

## 3. Create the Streamlit app

In Streamlit Community Cloud, create an app with the deployment coordinates
above. Select Python 3.12 and paste the hosted values from
`.streamlit/secrets.toml.template` into Advanced settings -> Secrets. Replace
the direct database URL with the provider's pooled URL before saving.

Do not upload a localhost URL or commit `.streamlit/secrets.toml` to GitHub.

## 4. Verify

After deployment:

1. Confirm `/` opens the Evercrest Health EHR.
2. Confirm `/` redirects to `/patientchart`.
3. Confirm the patient selector is populated.
4. Ask a medication question and confirm a grounded response.
5. Confirm the trace appears in the configured Galileo log stream.
