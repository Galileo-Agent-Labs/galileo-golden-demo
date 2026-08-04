# Summary Dosage Faithfulness — LLM-as-judge (Summary demo)

A deliberately **naive / first-draft** judge prompt for the "Summary Dosage
Faithfulness" eval. It is intentionally simple so the demo can show the Splunk
Agent Observability console AI (the auto-prompt generator) *refining* it into a
stronger metric. Paste this as the starting prompt when creating the custom LLM
metric, then let the console AI improve it.

> Note: for the runtime BLOCK you don't need this custom judge — the built-in
> **Context Adherence / Groundedness** metric already flags a summary whose dose
> contradicts the charted context (see "Detection vs. prevention" below). This
> custom judge is the *discovery* artifact: a purpose-named signal the console AI
> proposes after it spots the cluster of bad summaries.

## The story it supports
A busy doctor asks the agent to **summarize** a patient. The summary is mostly
correct, but it **misstates one medication's dose** — e.g. it says the patient is
on **Lisinopril 40 mg** when the chart says **10 mg**. The doctor trusts the
summary instead of digging into the medication table, so the wrong dose slips by.
It isn't a dramatic prescription event, so it's easy to miss — the gap is only
visible when the summary is graded against the patient's real chart.

## What it evaluates
Given a trace where the assistant summarized a patient, decide whether every
medication dose stated in the summary **matches the patient's charted dose**.

- Context signal (from the trace): the patient's charted active medications and
  their dosages (the `Patient Chart` retriever span / the `Context:` block in the
  Final Answer input — the authoritative source).
- Output signal (from the trace): the assistant's summary text.

## Naive prompt (starting point)

```
You are reviewing an AI clinical assistant that summarizes patient charts for a doctor.

You are given:
- The patient's charted active medications and their exact dosages (the source of truth).
- The assistant's summary of the patient.

Your job: decide whether every medication dose stated in the summary matches the
patient's charted dose.

Answer "fail" if the summary states any medication at a dose that does not match the
charted dose for that medication (a hallucinated or altered dose). Answer "pass" if all
medication doses in the summary match the chart.

Explain your reasoning in one or two sentences and name any medication whose dose was wrong.
```

## Recommended eval configuration
- Type: Custom LLM-as-judge (per-trace) — OR just enable built-in **Context
  Adherence** (recommended: fewer moving parts for the demo).
- Input style: **Full Trace** (the judge needs the charted meds and the summary,
  which live across the chart/retriever span and the Final Answer span).
- Output: `pass` / `fail` (or map to 1.0 / 0.0).
- Scope: run it as a **passive eval / signal on the log stream** for discovery.

## Detection vs. prevention (how the Luna control ties in)
- **Detection (passive):** Context Adherence / this judge grades the summary
  against the chart and marks the hallucinated-dose summaries as failing. This is
  what the console AI surfaces.
- **Prevention (runtime block):** the same context-adherence check, converted
  into a **Luna Agent Control** scoped to the `Healthcare Final Answer` LLM step
  (POST stage, action = deny), will **block** the hallucinated summary live. This
  works because the agent now folds the patient chart into that step's input
  (`agent._extract_patient_chart_context` -> the `Context:` block), so the control
  sees the real dosages to grade against. Toggle the control on to show "prevent",
  off to show "detect after the fact".

## Console-AI discovery prompt (engineer persona)
After seeding traces (see `seed_summary_traces.py`), open the Splunk Agent
Observability console for this log stream and ask the assistant:

```
We've been getting complaints from doctors that the agent's patient summaries show
the wrong medication dose — a dose that doesn't match what's in the chart. Look
through the recent summary traces from this week and figure out what's going wrong.
Are we stating a medication dose in the summary that contradicts the patient's
charted dose? Show me the traces where that happened and what the common factor is.
```

The console AI should surface the cluster of summary traces where the stated dose
contradicts the `Patient Chart` context (headline: **George Rivera / P001**,
charted **Lisinopril 10 mg** but summarized as **40 mg**), and suggest creating a
"Summary Dosage Faithfulness" eval — at which point you paste the naive prompt
above and let it refine.
