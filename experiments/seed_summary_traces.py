"""
Seed a realistic mix of *patient-summary* traces for the summary-hallucination demo.

The fail path in this demo is NOT a prescription — it's the agent hallucinating a
medication DOSE inside an otherwise-correct patient summary. A busy doctor trusts
the summary instead of digging into the chart, so a wrong dose (e.g. "Lisinopril
40 mg" when the chart says 10 mg) slips by. It is caught by a context-adherence
eval/control that grades the summary against the patient's real chart.

This script emits several trace categories in demo-tuned proportions so a fresh log
stream reads as mostly-healthy with a discoverable cluster of bad summaries that the
Splunk Agent Observability console AI can surface ("docs are complaining about wrong
summaries — what's going on?"):

  healthy_summary      (~58%) — doctor asks to summarize; agent reads the chart and
                                writes an accurate summary (all doses match the chart).
  summary_hallucination(~22%) — the fail cluster: the summary misstates ONE med's
                                dose vs. the chart (a genuine hallucination relative
                                to THIS patient, not a guideline range). Concentrated
                                in the most recent window ("complaints this week").
  medicine_qa          (~10%) — a grounded medicine Q&A (RAG) answer (variety).
  healthy_refill       (~10%) — a correct refill (variety; non-summary activity).

Each summary trace mirrors the LIVE trace shape so the metric grades them the same:
    get_patient_chart (tool)  ->  Patient Chart (retriever: the charted meds as the
    authoritative context docs)  ->  "Healthcare Final Answer" (llm: input embeds the
    same chart context, output is the summary text).

Traces are logged directly with GalileoLogger (no live LLM/agent run), so seeding is
deterministic, cheap, and independent of the Streamlit session. Each trace is
backdated to a random business-hours moment within the last ``--days`` and flushed
immediately (so an interrupted run still leaves complete, non-empty sessions).

Usage (from the project root, venv active, DB reachable read-only):
    python experiments/seed_summary_traces.py --count 60
    python experiments/seed_summary_traces.py --count 80 --days 10 \
        --project "Evercrest Summary" --log-stream "summary-agent"
    python experiments/seed_summary_traces.py --dry-run          # preview, log nothing
"""
import argparse
import json
import os
import random
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import setup_env  # noqa: E402  (injects truststore + loads secrets)
from domain_manager import DomainManager  # noqa: E402
from helpers.galileo_api_helpers import create_galileo_logger  # noqa: E402
from helpers.sql_utils import execute_sql, relational_table_name  # noqa: E402

DOMAIN = "healthcare"

# Small dosing knowledge base for the medicine_qa / refill variety traces.
GUIDELINES = {
    "Lisinopril":   {"cls": "ACE inhibitor",            "dose": "10-40 mg once daily",     "typical": "10 mg once daily",   "uses": "hypertension"},
    "Atorvastatin": {"cls": "Statin",                   "dose": "10-80 mg once daily",     "typical": "20 mg once daily",   "uses": "high cholesterol"},
    "Metformin":    {"cls": "Biguanide",                "dose": "500-1000 mg twice daily", "typical": "500 mg twice daily", "uses": "type 2 diabetes"},
    "Levothyroxine":{"cls": "Thyroid hormone",          "dose": "50-100 mcg once daily",   "typical": "75 mcg once daily",  "uses": "hypothyroidism"},
    "Amlodipine":   {"cls": "Calcium channel blocker",  "dose": "5-10 mg once daily",      "typical": "5 mg once daily",    "uses": "hypertension"},
    "Metoprolol":   {"cls": "Beta blocker",             "dose": "25-100 mg twice daily",   "typical": "50 mg twice daily",  "uses": "hypertension"},
}

# The flagship hallucination: pin George Rivera (P001, Lisinopril 10 mg) so the
# headline example matches the app's default (chart 10 mg -> summary 40 mg).
FLAGSHIP_PID = "P001"
FLAGSHIP_DRUG = "Lisinopril"
FLAGSHIP_WRONG_DOSE = "40 mg once daily"

_SUMMARY_TEMPLATES = [
    "Give me a brief summary of this patient — active meds, recent history, and anything I should know.",
    "Summarize {name} ({pid}) for me before my next appointment.",
    "Quick summary of {name}'s chart, please — what are they on right now?",
    "I'm short on time — summarize {name}'s active medications and history.",
    "Catch me up on {name} ({pid}) — meds and anything notable.",
]
_QA_TEMPLATES = [
    "What's the standard dosing for {drug}?",
    "Remind me of the usual {drug} dose and what it's used for.",
    "What are the common side effects and dosage of {drug}?",
]
_REFILL_TEMPLATES = [
    "Refill {name}'s {drug}.",
    "{name} ({pid}) is due for a {drug} refill — can you send it?",
    "Please renew {drug} for {name}.",
]


def _kb_line(drug: str) -> str:
    g = GUIDELINES[drug]
    return f"{drug} — Drug Class: {g['cls']} | Common Dosage: {g['dose']} | Uses: {g['uses']}"


# ---------------------------------------------------------------------------
# DB helpers (patients + charts) — read-only; never mutates the database.
# ---------------------------------------------------------------------------
def _all_patients() -> list[str]:
    pat = relational_table_name(DOMAIN, "patient")
    res = execute_sql(f'SELECT patient_id FROM "{pat}" ORDER BY patient_id')
    rows = res.get("rows", []) if isinstance(res, dict) else []
    return [r["patient_id"] for r in rows]


def _patient_chart(pid: str) -> dict:
    pat = relational_table_name(DOMAIN, "patient")
    med = relational_table_name(DOMAIN, "medication")
    demo = execute_sql(f"SELECT * FROM \"{pat}\" WHERE patient_id = '{pid}'")
    demo_rows = demo.get("rows", []) if isinstance(demo, dict) else []
    meds = execute_sql(
        f"SELECT medication, dosage, status FROM \"{med}\" "
        f"WHERE patient_id = '{pid}' AND status = 'active' ORDER BY start_date"
    )
    med_rows = meds.get("rows", []) if isinstance(meds, dict) else []
    return {
        "patient_id": pid,
        "demographics": demo_rows[0] if demo_rows else {},
        "active_medications": med_rows,
    }


def _name_of(chart: dict) -> str:
    return chart["demographics"].get("patient_name", chart["patient_id"])


def _who(chart: dict) -> str:
    name = str(_name_of(chart)).strip()
    pid = chart["patient_id"]
    return f"{name} [{pid}]" if name else pid


def _chart_context_docs(chart: dict) -> list[str]:
    """The charted meds as authoritative context docs.

    MUST match ``agent._extract_patient_chart_context`` so seeded traces are graded
    by Context Adherence exactly like live ones.
    """
    who = _who(chart)
    docs = []
    for m in chart["active_medications"]:
        drug = str(m.get("medication") or "").strip()
        if not drug:
            continue
        dose = str(m.get("dosage") or "").strip()
        status = str(m.get("status") or "active").strip()
        docs.append(
            f"Patient chart (authoritative source) for {who} — active medication: "
            f"{drug} {dose} (status: {status})."
        )
    return docs


def _bump_dose(dose: str) -> str:
    """Return a plausible-but-wrong dose by scaling the first number up.

    Keeps units/frequency ("10 mg once daily" -> "20 mg once daily") so the
    hallucination is subtle — a real-looking dose that simply isn't this
    patient's charted one.
    """
    m = re.search(r"(\d+(?:\.\d+)?)", dose)
    if not m:
        return dose
    val = float(m.group(1))
    bumped = val * 2
    bumped_str = str(int(bumped)) if bumped.is_integer() else str(bumped)
    return dose[: m.start()] + bumped_str + dose[m.end():]


def _summary_text(chart: dict, wrong: dict | None = None) -> str:
    """Build a bullet summary. If ``wrong`` = {medication, dosage}, that med's dose
    is replaced with the wrong value (the hallucination); everything else is true.
    """
    name = _name_of(chart)
    demo = chart["demographics"]
    ptype = str(demo.get("patient_type") or "").strip()
    header = f"Summary for {name} ({chart['patient_id']})"
    if ptype:
        header += f", {ptype}"
    lines = [header + ":", "", "Active medications:"]
    for m in chart["active_medications"]:
        drug = m.get("medication", "")
        dose = m.get("dosage", "")
        if wrong and drug == wrong["medication"]:
            dose = wrong["dosage"]
        lines.append(f"  • {drug} — {dose}")
    lines.append("")
    lines.append(
        "History reviewed; no new acute issues noted. Continue current regimen and "
        "reassess at next visit."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Timestamp spread
# ---------------------------------------------------------------------------
def _random_business_dt(days: int, recent_bias: bool = False, no_backdate: bool = False) -> datetime:
    now = datetime.now(timezone.utc)
    if no_backdate:
        return now
    span = max(days, 1)
    day_offset = random.uniform(0, span / 3.0) if recent_bias else random.uniform(0, span)
    dt = now - timedelta(days=day_offset)
    return dt.replace(hour=random.randint(8, 17), minute=random.randint(0, 59),
                      second=random.randint(0, 59), microsecond=0)


class _Clock:
    """Hands out increasing per-span created_at timestamps within one trace."""

    def __init__(self, base: datetime):
        self.t = base

    def tick(self, duration_ns: int) -> datetime:
        cur = self.t
        self.t = self.t + timedelta(microseconds=duration_ns / 1000.0)
        return cur

    def elapsed_ns(self, base: datetime) -> int:
        return int((self.t - base).total_seconds() * 1e9)


# ---------------------------------------------------------------------------
# Trace emitters
# ---------------------------------------------------------------------------
def _emit_summary(gl, chart: dict, base: datetime, wrong: dict | None) -> str:
    """A summarize turn. If ``wrong`` is set, the summary misstates that med's dose."""
    pid, name = chart["patient_id"], _name_of(chart)
    request = random.choice(_SUMMARY_TEMPLATES).format(name=name, pid=pid)
    context_docs = _chart_context_docs(chart)
    summary = _summary_text(chart, wrong)
    demo_type = "summary_hallucination" if wrong else "healthy_summary"
    clk = _Clock(base)

    gl.start_session(name="EHR — Summary", external_id=str(uuid.uuid4())[:10])
    meta = {"demo_type": demo_type}
    if wrong:
        meta.update({"drug": wrong["medication"], "charted_dose": wrong["charted"],
                     "summary_dose": wrong["dosage"]})
    gl.start_trace(input=request, name="Patient summary", created_at=base,
                   metadata=meta, tags=["healthcare", "summary"])

    gl.add_tool_span(input=json.dumps({"patient_id": pid}), output=json.dumps(chart),
                     name="get_patient_chart", created_at=clk.tick(int(9e7)),
                     duration_ns=int(9e7), tags=["healthcare", "tool"])
    # The chart as authoritative context so Context Adherence can grade the summary.
    gl.add_retriever_span(input=f"Chart for {pid}", output=context_docs,
                          name="Patient Chart", created_at=clk.tick(int(6e7)),
                          duration_ns=int(6e7), status_code=200)
    # Mirror _review_final_answer's luna_input so runtime + offline grading match.
    llm_input = "Context:\n" + "\n\n".join(context_docs) + f"\n\nQuestion:\n{request}"
    gl.add_llm_span(input=llm_input, output=summary, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.4e8)),
                    duration_ns=int(1.4e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(summary.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(summary.split())) * 2,
                    metadata=meta, time_to_first_token_ns=500000)
    gl.conclude(output=summary, duration_ns=clk.elapsed_ns(base), status_code=200)
    return demo_type


def _emit_medicine_qa(gl, chart: dict, base: datetime) -> str:
    drug = random.choice(list(GUIDELINES))
    g = GUIDELINES[drug]
    request = random.choice(_QA_TEMPLATES).format(drug=drug)
    clk = _Clock(base)

    gl.start_session(name="EHR — Medicine Q&A", external_id=str(uuid.uuid4())[:10])
    gl.start_trace(input=request, name="Medicine question", created_at=base,
                   metadata={"demo_type": "medicine_qa", "drug": drug}, tags=["healthcare"])
    gl.add_retriever_span(input=f"{drug} dosage and uses", output=[_kb_line(drug)],
                          name="Retrieve Medicine Information", created_at=clk.tick(int(1.1e8)),
                          duration_ns=int(1.1e8), status_code=200)
    answer = (f"{drug} is a {g['cls'].lower()} used for {g['uses']}. The usual dosage is "
              f"{g['dose']}. Always confirm against the patient's chart before prescribing.")
    llm_input = f"Reference:\n{_kb_line(drug)}\n\nQuestion: {request}"
    gl.add_llm_span(input=llm_input, output=answer, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.2e8)),
                    duration_ns=int(1.2e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(answer.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(answer.split())) * 2,
                    metadata={"demo_type": "medicine_qa"}, time_to_first_token_ns=500000)
    gl.conclude(output=answer, duration_ns=clk.elapsed_ns(base), status_code=200)
    return "medicine_qa"


def _emit_healthy_refill(gl, chart: dict, base: datetime) -> str:
    pid, name = chart["patient_id"], _name_of(chart)
    known = [m["medication"] for m in chart["active_medications"] if m["medication"] in GUIDELINES]
    drug = random.choice(known) if known else random.choice(list(GUIDELINES))
    g = GUIDELINES[drug]
    dose = g["typical"]
    request = random.choice(_REFILL_TEMPLATES).format(name=name, pid=pid, drug=drug)
    clk = _Clock(base)

    gl.start_session(name="EHR — Refill", external_id=str(uuid.uuid4())[:10])
    gl.start_trace(input=request, name="Refill request", created_at=base,
                   metadata={"demo_type": "healthy_refill", "drug": drug}, tags=["healthcare"])
    gl.add_tool_span(input=json.dumps({"patient_id": pid}), output=json.dumps(chart),
                     name="get_patient_chart", created_at=clk.tick(int(9e7)),
                     duration_ns=int(9e7), tags=["healthcare", "tool"])
    gl.add_retriever_span(input=f"{drug} dosage guideline", output=[_kb_line(drug)],
                          name="Retrieve Medicine Information", created_at=clk.tick(int(1.1e8)),
                          duration_ns=int(1.1e8), status_code=200)
    confirmation = f"RX-{uuid.uuid4().hex[:10].upper()}"
    final_reply = (
        f"Done — {drug} {dose} sent to {name}'s pharmacy (confirmation {confirmation}) "
        f"as a 30-day supply. The dose matches the current guideline."
    )
    llm_input = f"Guideline:\n{_kb_line(drug)}\n\nDoctor request: {request}"
    gl.add_llm_span(input=llm_input, output=final_reply, model="gpt-4o",
                    name="Healthcare Final Answer", created_at=clk.tick(int(1.3e8)),
                    duration_ns=int(1.3e8), temperature=0.1, status_code=200,
                    num_input_tokens=len(llm_input.split()) * 2,
                    num_output_tokens=len(final_reply.split()) * 2,
                    total_tokens=(len(llm_input.split()) + len(final_reply.split())) * 2,
                    metadata={"demo_type": "healthy_refill"}, time_to_first_token_ns=500000)
    gl.conclude(output=final_reply, duration_ns=clk.elapsed_ns(base), status_code=200)
    return "healthy_refill"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
_WEIGHTS = {
    "healthy_summary": 0.58,
    "summary_hallucination": 0.22,
    "medicine_qa": 0.10,
    "healthy_refill": 0.10,
}


def _plan_counts(total: int) -> dict:
    counts = {k: int(round(total * w)) for k, w in _WEIGHTS.items()}
    drift = total - sum(counts.values())
    counts["healthy_summary"] += drift
    return counts


def _pick_hallucination(chart: dict) -> dict | None:
    """Choose which charted med the summary will misstate, and the wrong dose."""
    meds = [m for m in chart["active_medications"] if m.get("medication")]
    if not meds:
        return None
    # Prefer the flagship drug when the patient is on it (headline example).
    flagship = [m for m in meds if m["medication"] == FLAGSHIP_DRUG]
    med = flagship[0] if flagship else random.choice(meds)
    charted = str(med.get("dosage") or "").strip()
    if med["medication"] == FLAGSHIP_DRUG:
        wrong_dose = FLAGSHIP_WRONG_DOSE
    else:
        wrong_dose = _bump_dose(charted)
    if wrong_dose == charted:  # nothing changed; not a hallucination
        return None
    return {"medication": med["medication"], "dosage": wrong_dose, "charted": charted}


def _load_project_stream(cli_project, cli_stream):
    dm = DomainManager(domains_dir=str(_ROOT / "domains"))
    dcfg = dm.load_domain_config(DOMAIN)
    setup_env.setup_environment(DOMAIN, dcfg.config)
    g = dcfg.config.get("galileo", {})
    # Prefer the secrets/env override (GALILEO_PROJECT / GALILEO_LOG_STREAM) so one
    # secrets change drives both the hosted app and the seeder, then config.yaml.
    project = cli_project or os.environ.get("GALILEO_PROJECT") or g.get("project", "galileo-demo-healthcare")
    stream = cli_stream or os.environ.get("GALILEO_LOG_STREAM") or g.get("log_stream", "default")
    return project, stream


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=60, help="Total traces to seed")
    parser.add_argument("--days", type=int, default=7, help="Backdate window (days)")
    parser.add_argument("--project", default=None, help="Override Galileo project (else secrets/config)")
    parser.add_argument("--log-stream", default=None, help="Override log stream (else secrets/config)")
    parser.add_argument("--seed", type=int, default=7, help="RNG seed for reproducibility")
    parser.add_argument("--no-backdate", action="store_true",
                        help="Timestamp everything now (avoids console time-filter surprises)")
    parser.add_argument("--dry-run", action="store_true", help="Preview the plan; log nothing")
    args = parser.parse_args()

    random.seed(args.seed)
    project, log_stream = _load_project_stream(args.project, args.log_stream)
    counts = _plan_counts(args.count)

    all_patients = _all_patients()
    if not all_patients:
        print("No patients found — is the healthcare relational data loaded?")
        sys.exit(1)

    print(f"Seeding {args.count} summary-demo traces over the last {args.days} day(s)")
    print(f"  project    = {project}")
    print(f"  log stream = {log_stream}")
    print(f"  patients   = {len(all_patients)} total  (flagship: {FLAGSHIP_PID}/{FLAGSHIP_DRUG})")
    print("  plan:")
    for k, v in counts.items():
        print(f"    {k:22s} {v}")

    if args.dry_run:
        print("\n--dry-run: nothing was logged.")
        return

    gl = create_galileo_logger(project, log_stream)

    # Build a chronological work list. The hallucination cluster is recent-biased.
    work: list[tuple[str, datetime]] = []
    for _ in range(counts["healthy_summary"]):
        work.append(("healthy_summary", _random_business_dt(args.days, no_backdate=args.no_backdate)))
    for _ in range(counts["medicine_qa"]):
        work.append(("medicine_qa", _random_business_dt(args.days, no_backdate=args.no_backdate)))
    for _ in range(counts["healthy_refill"]):
        work.append(("healthy_refill", _random_business_dt(args.days, no_backdate=args.no_backdate)))
    for _ in range(counts["summary_hallucination"]):
        work.append(("summary_hallucination",
                     _random_business_dt(args.days, recent_bias=True, no_backdate=args.no_backdate)))
    work.sort(key=lambda x: x[1])

    seeded = {k: 0 for k in counts}
    for i, (category, base) in enumerate(work, 1):
        try:
            if category == "medicine_qa":
                _emit_medicine_qa(gl, _patient_chart(random.choice(all_patients)), base)
            elif category == "healthy_refill":
                _emit_healthy_refill(gl, _patient_chart(random.choice(all_patients)), base)
            elif category == "healthy_summary":
                _emit_summary(gl, _patient_chart(random.choice(all_patients)), base, wrong=None)
            elif category == "summary_hallucination":
                # Bias toward the flagship patient so the headline example is always present.
                pid = FLAGSHIP_PID if random.random() < 0.4 else random.choice(all_patients)
                chart = _patient_chart(pid)
                wrong = _pick_hallucination(chart)
                if not wrong:  # patient had no usable med; fall back to a healthy summary
                    _emit_summary(gl, chart, base, wrong=None)
                    seeded["healthy_summary"] += 1
                    gl.flush()
                    continue
                _emit_summary(gl, chart, base, wrong=wrong)
            seeded[category] += 1
            # Flush per trace so an interrupted run still leaves complete sessions.
            gl.flush()
            print(f"  [{i}/{len(work)}] {category} @ {base:%Y-%m-%d %H:%M}")
        except Exception as e:  # keep going; report at the end
            print(f"  [{i}/{len(work)}] FAILED {category}: {e}")

    gl.flush()
    print("\nDone. Seeded:")
    for k, v in seeded.items():
        print(f"  {k:22s} {v}")
    print("\nConsole discovery prompt (engineer persona):")
    print("  'Docs are complaining the agent's patient summaries have the wrong "
          "medication dose. Is there a problem, and which summaries are affected?'")
    print("  (see experiments/summary_dosage_faithfulness_judge_prompt.md)")


if __name__ == "__main__":
    main()
