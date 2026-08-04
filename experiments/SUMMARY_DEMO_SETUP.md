# Summary-Hallucination Demo — setup & run guide

This branch (`summary-hallucination-demo`) reframes the healthcare fail path away
from a scary "agent sends a prescription" scenario to a subtler, safer one: the
agent **hallucinates a medication dose inside a patient summary**. A busy doctor
trusts the summary instead of digging into the chart, so a wrong dose (e.g.
*Lisinopril 40 mg* when the chart says *10 mg*) slips by. It's caught by a
context-adherence eval/control that grades the summary against the patient's real
chart.

Nothing here writes to the database — summarizing is **read-only**, so this runs
against the **same Neon DB** without disturbing the existing (prescription) demo.

## What changed in code
- `chaos_engine.py` — new **`hallucinate_summary_dosage`** mode
  (`enable_hallucinate_summary` / `should_hallucinate_summary` /
  `get_summary_hallucination_prompt`). Injects a directive so the summary misstates
  one med's dose (default **Lisinopril → 40 mg once daily**), pinned to the demo
  patient for determinism.
- `agent_frameworks/langgraph/agent.py` — **the linchpin**:
  `_extract_patient_chart_context()` now surfaces `get_patient_chart`'s active meds
  as authoritative **context** and folds them into the `Healthcare Final Answer`
  review input. Previously only RAG snippets counted as context, so a summary had
  nothing to be graded against. Now both the offline **Context Adherence** metric
  and the runtime **Luna control** can compare the summary's doses to the chart.
- `app.py` — sidebar toggle **"📋 Hallucinate Summary Dosage (Summary demo)"**
  (ON by default). The legacy "Force Wrong Dosage (prescribe/refill)" toggle is now
  OFF by default so the headline fail path is the summary.
- `experiments/seed_summary_traces.py` — seeds a realistic mix of summary traces
  (mostly accurate + a recent cluster of hallucinated-dose summaries).
- `experiments/summary_dosage_faithfulness_judge_prompt.md` — discovery prompt +
  naive judge prompt for the console-AI beat.

## Hosting (separate app, same Neon read-only)
Deploy a new Streamlit Cloud app from the `summary-hallucination-demo` branch. Use
its own secrets (copy the current hosted secrets, then change only the Galileo
target so Paul's stream is untouched):

```toml
default_domain = "healthcare"
environment    = "hosted"
# --- unchanged: same Neon, read-only for this demo ---
postgres_url   = "postgresql://…neon.tech/neondb?sslmode=require"
postgres_sslmode = "require"
# --- new, isolated Galileo target for THIS demo ---
galileo_project    = "Evercrest Summary Demo"   # a NEW project
galileo_log_stream = "summary-agent"            # a NEW log stream
# …keep the existing openai_/galileo_/agent_control_ keys…
```

`galileo_project` / `galileo_log_stream` in secrets override `config.yaml` for both
the app and the seeder, so one change points everything at the new stream.

## Metrics to switch ON (keep it minimal)
On the new log stream, enable just:
1. **Context Adherence** (a.k.a. Groundedness) — the star. Flags a summary whose
   dose contradicts the charted context. This is what detects the hallucination.
2. *(optional)* **Summary Dosage Faithfulness** — a custom LLM-as-judge for a
   demo-friendly, purpose-named signal (paste the naive prompt from
   `summary_dosage_faithfulness_judge_prompt.md`, then let the console AI refine).

Leave other evals off to avoid distracting viewers.

## Control setup (Luna context-adherence, for the "prevent" beat)
Create/attach a **Luna context-adherence control** on the new log stream:
- Scope: **LLM** step, step name **`Healthcare Final Answer`**, stage **POST**.
- Evaluator: context-adherence / groundedness (Luna).
- Action: **deny** (blocks the summary when it isn't grounded in the chart context).

Because the agent now embeds the chart into that step's input, the control has the
real dosages to grade against and will block a summary that invents a dose.
- **Toggle OFF** → summary slips through; Context Adherence flags it after the fact
  (the "we didn't catch it live" discovery story).
- **Toggle ON** → the hallucinated summary is blocked live (the "prevent" story).

## Seed the log stream
From the project root, venv active, DB reachable (read-only):

```bash
venv/bin/python3 experiments/seed_summary_traces.py --count 60 --days 7
# preview only:
venv/bin/python3 experiments/seed_summary_traces.py --dry-run
```

It seeds ~58% accurate summaries, a recent-biased ~22% hallucinated-dose cluster
(headline: **George Rivera / P001**, charted 10 mg → summarized 40 mg), plus a bit
of Q&A/refill variety. Each trace is flushed immediately, so an interrupted run
still leaves complete sessions.

## Live demo flow
1. Open the EHR app (new host), select **George Rivera (P001)**.
2. Click **📋 Summarize patient history**. With the summary-hallucination toggle ON,
   the summary states **Lisinopril 40 mg** though the chart shows **10 mg**.
   - **Control OFF:** the wrong summary is shown (doctor is busy, trusts it) →
     switch to the console: Context Adherence has flagged this trace.
   - **Control ON:** the summary is **blocked** live by the Luna control.
3. **Console-AI discovery (engineer persona):** open the console for this log stream
   and paste the discovery prompt from
   `summary_dosage_faithfulness_judge_prompt.md` ("docs are complaining about wrong
   summary doses…"). The assistant surfaces the cluster of summaries whose stated
   dose contradicts the `Patient Chart` context and proposes the eval.
