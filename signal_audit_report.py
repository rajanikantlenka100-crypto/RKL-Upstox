"""Print the append-only signal audit in a GPT-reviewable format."""

from signals.audit import SignalAudit


if __name__ == "__main__":
    from config import ROOT

    print(SignalAudit(ROOT / "logs" / "signal_audit.jsonl").report())