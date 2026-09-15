"""Persistent operational telemetry and daily verification reports."""

import json
import time
from collections import Counter
from datetime import datetime
from uuid import uuid4


STATUSES = {"PASS", "FAILED", "NOT TESTED", "NOT OBSERVED"}


class Observability:
    def __init__(self, store, component="SYSTEM"):
        self.store = store
        self.component = component
        self.started_at = datetime.now().astimezone()
        self._last_heartbeat = 0.0

    def event(self, event_type, *, component=None, severity="INFO", message="", exception="",
              system_state="", recovery_action="", resolution="UNRESOLVED", payload=None,
              timestamp=None):
        self.store.record_telemetry(str(uuid4()), {
            "timestamp": (timestamp or datetime.now().astimezone()).isoformat(),
            "severity": severity, "component": component or self.component,
            "event_type": event_type, "message": message, "exception": exception,
            "system_state": system_state, "recovery_action": recovery_action,
            "resolution": resolution, "payload": payload or {},
        })

    def timed(self, event_type, action, *, component=None, payload=None):
        started = time.perf_counter()
        try:
            result = action()
        except Exception as error:
            self.event(event_type, component=component, severity="ERROR", exception=repr(error),
                       message=str(error), payload={**(payload or {}), "latency_ms": round((time.perf_counter() - started) * 1000, 3), "success": False})
            raise
        self.event(event_type, component=component, payload={**(payload or {}),
                   "latency_ms": round((time.perf_counter() - started) * 1000, 3), "success": True})
        return result

    def heartbeat(self, snapshot):
        now = time.monotonic()
        if now - self._last_heartbeat < 1:
            return
        self._last_heartbeat = now
        self.event("HEARTBEAT", payload=snapshot, resolution="OBSERVED")

    def daily_report(self, report_date=None):
        report_date = report_date or datetime.now().astimezone().date().isoformat()
        rows = self.store.telemetry_events(report_date)
        events = []
        for row in rows:
            payload = json.loads(row[9] or "{}")
            events.append({"timestamp": row[0], "severity": row[1], "component": row[2],
                           "event_type": row[3], "message": row[4], "exception": row[5],
                           "system_state": row[6], "recovery_action": row[7],
                           "resolution": row[8], "payload": payload})
        def section(component, required=()):
            selected = [item for item in events if item["component"] == component]
            observed = {item["event_type"] for item in selected}
            if not selected:
                status = "NOT OBSERVED"
            elif any(item["severity"] in {"ERROR", "CRITICAL", "HALT"} for item in selected):
                status = "FAILED"
            elif required and not set(required).issubset(observed):
                status = "NOT TESTED"
            else:
                status = "PASS"
            return {"status": status, "events": len(selected),
                    "event_types": dict(Counter(item["event_type"] for item in selected))}

        order_events = [item for item in events if item["component"] == "ORDERS"]
        broker_accepts = any(item["event_type"] in {"ORDER_ACCEPTED", "ORDER_FILLED"} for item in order_events)
        fills = any(item["event_type"] == "ORDER_FILLED" for item in order_events)
        report = {
            "report_date": report_date,
            "generated_at": datetime.now().astimezone().isoformat(),
            "system_uptime_seconds": max(0, (datetime.now().astimezone() - self.started_at).total_seconds()),
            "status": "PASS" if events and not any(item["severity"] in {"CRITICAL", "HALT"} for item in events) else ("FAILED" if events else "NOT OBSERVED"),
            "sections": {
                "AUTH": section("AUTH", ("AUTH_START", "AUTH_END")),
                "WEBSOCKET": section("WEBSOCKET"), "HISTORY": section("HISTORY"),
                "CANDLES": section("CANDLES"), "SIGNALS": section("SIGNALS"),
                "OPTIONS": section("OPTIONS"), "ORDERS": section("ORDERS"),
                "SYSTEM": section("SYSTEM"),
            },
            "order_verification": {
                "ORDER REQUEST REACHED BROKER": "PASS" if any(item["event_type"] == "ORDER_REQUEST_SENT" for item in order_events) else "NOT OBSERVED",
                "BROKER ACCEPTED/FILLED": "PASS" if broker_accepts else ("FAILED" if any(item["event_type"] == "ORDER_REJECTED" for item in order_events) else "NOT TESTED"),
                "SL/FILL LIFECYCLE": "PASS" if fills else "NOT TESTED",
                "reason": next((item["message"] for item in order_events if item["event_type"] == "ORDER_REJECTED"), ""),
            },
            "latency_statistics": {"observations": [item["payload"] for item in events if "latency_ms" in item["payload"]]},
            "broker_errors": [item for item in events if item["component"] == "BROKER" and item["severity"] in {"ERROR", "CRITICAL"}],
            "runtime_errors": [item for item in events if item["severity"] in {"ERROR", "CRITICAL", "HALT"}],
            "halts_recoveries": [item for item in events if item["severity"] in {"HALT", "RECOVERY"}],
        }
        self.store.save_daily_report(report_date, report)
        return report