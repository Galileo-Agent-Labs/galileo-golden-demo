# Evercrest Streamlit deployment runbook

Last verified: 2026-08-03

This is the canonical operations guide for the two Evercrest apps hosted in
Streamlit Community Cloud. It covers access, configuration, routine updates,
new deployments, secret rotation, rollback, and validation.

## Deployment inventory

Both apps are independent Streamlit deployments from the same GitHub
repository. Each app follows its own branch and updates automatically when that
branch is pushed.

| App | Public URL | Git branch | Entrypoint | Python | Landing route |
| --- | --- | --- | --- | --- | --- |
| Evercrest patient chart | <https://evercrest-demo.streamlit.app/patientchart> | `codex/evercrest-streamlit` | `app.py` | 3.12 | `/patientchart` |
| Evercrest EHR v2 | <https://evercrest-demo-v2.streamlit.app/> | `evercrest-ehr-frontend` | `app.py` | 3.12 | `/` |

Shared coordinates:

- GitHub repository: `Galileo-Agent-Labs/galileo-golden-demo`
- Streamlit workspace: `galileo-agent-labs`
- Hosting: Streamlit Community Cloud
- Runtime database: shared hosted Neon PostgreSQL with pgvector and TLS
- Hosted model: OpenAI (`gpt-4o`)
- Embeddings: OpenAI `text-embedding-3-large`, 768 dimensions

The two UIs have separate code and release cycles, but they reuse the same
PostgreSQL healthcare data and RAG index. A push to `main` does **not** deploy
either app; only a push to the branch in the table above triggers that app.

## Architecture and configuration ownership

```text
GitHub: codex/evercrest-streamlit ──> evercrest-demo.streamlit.app
                                      /patientchart
                                   \
                                    +--> shared Neon PostgreSQL / pgvector
                                   /
GitHub: evercrest-ehr-frontend ────> evercrest-demo-v2.streamlit.app
                                      /
```

Configuration is divided deliberately:

- Git controls application code, dependencies, routing, and non-secret
  templates.
- Streamlit app settings control the selected branch, entrypoint, Python
  version, URL, and encrypted runtime secrets.
- 1Password is the source of truth for deployable credentials.
- Galileo controls projects, log streams, traces, and Agent Control policies.
- Neon hosts the shared PostgreSQL database and pgvector index.

The primary patient-chart app routes Galileo traffic to `demo-test` / `Agent`
and uses Agent Control agent `golden-demo-agent`. The EHR v2 branch routes to
`EHR Assistant` / `chart-agent` and uses `ehr-assistant-agent`. These defaults
are branch-specific even though the credential block and database are shared.

## Required access

Each operator should use their own account. Do not share personal GitHub,
Streamlit, Cisco, or Galileo login passwords.

An operator needs:

1. Membership in GitHub organization `Galileo-Agent-Labs` with write access to
   `galileo-golden-demo`.
2. Access to the Streamlit workspace `galileo-agent-labs`.
3. Access to the Cisco 1Password vault listed below.
4. Access to the relevant Galileo project if traces or Agent Control must be
   inspected.

## Secrets and 1Password

The canonical credential item is stored in the **Cisco** 1Password
organization:

- Account: `cisco.1password.com`
- Vault: `1P-Eng-Splunk-AI-Resilience`
- Vault ID: `lnvcpvdd5un3eoa6s72uiotysm`
- Item: `Galileo Golden Demo - Team Deployment (demo-v2)`
- Item ID: `74krvvljdnxea7jzi2ncqzglgy`
- Paste-ready Streamlit field: `STREAMLIT_SECRETS_TOML`
- Field ID: `deployment_27`
- 1Password reference:

  ```text
  op://lnvcpvdd5un3eoa6s72uiotysm/74krvvljdnxea7jzi2ncqzglgy/deployment_27
  ```

The reference uses vault, item, and field IDs because parentheses in the
human-readable item title are not valid in a CLI secret reference.

The item also contains concealed individual credentials such as
`OPENAI_API_KEY`, `GALILEO_API_KEY`, `POSTGRES_PASSWORD`, and deployment
metadata for both apps. The paste-ready TOML field is the authoritative value
for Streamlit.

Never commit real credentials, a resolved `.env`, or
`.streamlit/secrets.toml`.

### Copy secrets into Streamlit safely

Sign in to the Cisco account with the 1Password CLI, then copy the concealed
TOML directly to the clipboard:

```bash
op signin --account cisco.1password.com
op read \
  'op://lnvcpvdd5un3eoa6s72uiotysm/74krvvljdnxea7jzi2ncqzglgy/deployment_27' \
  | pbcopy
```

Paste the value into **Streamlit → Manage app → Settings → Secrets**, save it,
and immediately clear the clipboard:

```bash
pbcopy </dev/null
```

On Linux, use the equivalent secure clipboard command. Avoid printing the
field with `op read` directly into a shared terminal or shell history.

## Routine application update

Use the deployment branch for the app being changed. Do not make deployment
work on `main` and expect Streamlit to pick it up.

```bash
git clone git@github.com:Galileo-Agent-Labs/galileo-golden-demo.git
cd galileo-golden-demo
git fetch origin

# Choose exactly one deployment branch:
git switch codex/evercrest-streamlit
# or: git switch evercrest-ehr-frontend

git pull --ff-only
git switch -c your-name/short-change-description
```

Make the change, then validate at minimum:

```bash
python -m compileall -q app.py domains helpers
python -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
```

Run locally when the change affects UI, routing, prompts, tools, dependencies,
or database access:

```bash
streamlit run app.py
```

Open a pull request into the deployment branch. After review, merge and push
that branch. Streamlit normally detects the GitHub update automatically.

### Files commonly changed

- `app.py`: application routing, shared UI, assistant dialog, and session flow.
- `domains/healthcare/`: healthcare prompts, tools, data, and the EHR v2 theme.
- `agent_frameworks/langgraph/`: agent orchestration and tool execution.
- `helpers/`: database, RAG, model, Galileo, and Agent Control integration.
- `setup_env.py`: conversion of Streamlit secrets into process environment.
- `requirements.txt`: hosted Python dependencies.
- `.streamlit/config.toml`: Streamlit theme and non-secret runtime options.

Changes to shared agent or backend modules may need to be applied to **both**
deployment branches. Verify both apps before considering such a change done.

## Create or recreate an app

In <https://share.streamlit.io/>, switch to workspace
`galileo-agent-labs`, select **Create app → Deploy from repo**, and provide the
coordinates from the deployment inventory.

In **Advanced settings**:

1. Select Python 3.12.
2. Retrieve `STREAMLIT_SECRETS_TOML` from the Cisco 1Password item.
3. Paste it into the encrypted Secrets field.
4. Confirm the custom subdomain before selecting **Deploy**.

Secrets are scoped per Streamlit app. Creating a second app does not copy
secrets from the first app automatically.

Do **not** run `helpers/setup_vectordb.py` against the existing hosted database
when creating or recreating either app. The healthcare data and hosted RAG
index are already present. Re-seeding can overwrite or duplicate shared state.

## Streamlit settings changes

Open the app and select **Manage app**.

- **Settings → General** changes the URL or Python version.
- **Settings → Secrets** changes encrypted runtime configuration.
- The app menu provides logs, analytics, reboot, and delete operations.

Use **Reboot app** when Streamlit has not pulled a pushed commit or when a
secret/dependency update needs a clean process. Reboot interrupts current
users, so verify the intended app and branch first.

Never use **Delete app** as a troubleshooting step. It destroys the deployment
record and custom URL association.

## Secret rotation

Rotate one provider at a time:

1. Create or rotate the credential at the provider.
2. Update the corresponding concealed field in the Cisco 1Password item.
3. Update the paste-ready `STREAMLIT_SECRETS_TOML` field in the same item.
4. Paste the updated TOML into **both** Streamlit apps and save.
5. Wait for the settings update to propagate, then verify both apps.
6. Revoke the old provider credential only after both apps pass verification.

Edit concealed fields through the 1Password desktop or web UI. Avoid passing
secret values as command-line arguments because other local processes may see
them.

If the PostgreSQL URL is rotated, preserve the pooled Neon hostname and
`sslmode=require`. Both apps must be updated during the same maintenance
window because they share the database.

## Database and schema changes

Treat the Neon database as a shared production-like dependency:

- Prefer backward-compatible schema changes.
- Test migrations against a disposable database first.
- Deploy code that can handle both the old and new schema before applying a
  breaking migration.
- Back up or snapshot the database before destructive operations.
- Never log the connection URL or credentials.
- Do not rebuild the hosted vector index unless the embedding model,
  dimensions, or source corpus intentionally changed.

## Post-deployment verification

Verify the public URL, not only localhost.

For both apps:

1. The app loads without a Python exception.
2. The patient selector is populated and the chart shows medications/history.
3. Open the clinical assistant and select **Summarize this patient**.
4. The preset runs immediately and an assistant response appears.
5. The follow-up input appears after the first response.
6. Both the footer **Close** button and title-bar X dismiss the dialog.
7. A trace appears in the expected Galileo project and log stream.

Additional route checks:

- `evercrest-demo.streamlit.app/patientchart` must remain the patient-chart
  landing page.
- `evercrest-demo-v2.streamlit.app/` must show the alternate practitioner EHR
  with vitals, medications, laboratory results, and encounters.

## Rollback

Prefer a Git revert because it is auditable and preserves history:

```bash
git switch <deployment-branch>
git pull --ff-only
git revert <bad-commit-sha>
git push origin <deployment-branch>
```

Watch Streamlit logs until the reverted commit is running, then repeat the
post-deployment verification.

For a secret-only failure, restore the previous value from the 1Password item
history, save it in both Streamlit apps, and reboot only if the settings update
does not restart the affected process.

Do not use `git reset --hard` or force-push a deployment branch for routine
rollback. Do not roll back a database migration until its data compatibility
and backup state are understood.

## Troubleshooting

### Streamlit builds the wrong code

Open **Manage app** and confirm the displayed repository, branch, and
`app.py` path match the deployment inventory. A push to `main` does not update
either app.

### Secrets or TOML parsing error

Retrieve the full `STREAMLIT_SECRETS_TOML` field again instead of copying
individual lines. Confirm that no shell quoting or Markdown fences were pasted
into Streamlit.

### PostgreSQL or retrieval failure

Confirm that the shared Neon URL is present, uses the pooled endpoint, and
includes TLS (`sslmode=require`). Do not run the database setup script as a
first response. Check connection limits and hosted RAG index availability.

### UI click submits but no assistant response appears

Inspect Streamlit logs for fragment or full-app rerun errors. Dialog widgets
must queue work through callbacks and refresh the dialog fragment after the
response; a full-app rerun can invalidate the active dialog.

### Dependency fails only in Community Cloud

Confirm Python 3.12 and inspect the complete build log. Native packages such as
OpenCV may require headless variants or additional system libraries. Correct
the dependency declaration and push a tested commit; repeated rebooting does
not repair an incompatible wheel.

## Change record checklist

Record these details in the pull request or incident notes:

- App and deployment branch changed
- Commit SHA deployed
- Whether secrets changed
- Whether the database schema or RAG index changed
- Public verification results
- Galileo trace/project verification
- Rollback commit or restored 1Password version, if applicable
