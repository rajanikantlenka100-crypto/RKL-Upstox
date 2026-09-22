"""Single-owner signal coordination and approval lifecycle."""

import queue
import threading
import sys
from datetime import datetime, timedelta
from dataclasses import replace

_PRIMARY = {"NIFTY", "SENSEX"}
_PRIORITY = {"NIFTY": 0, "SENSEX": 1, "BANKNIFTY": 2, "MIDCPNIFTY": 3}


class SignalArbitrator:
    """Accept at most one executable signal per underlying and running candle."""

    def __init__(self):
        self.locks = {}
        self.lock = threading.RLock()

    def reset(self, underlying, candle_timestamp):
        with self.lock:
            self.locks.pop((underlying, candle_timestamp), None)

    def admit(self, candidates):
        if not candidates:
            return None, "NO_CANDIDATE"
        key = (candidates[0].underlying, candidates[0].timestamp)
        if any((candidate.underlying, candidate.timestamp) != key for candidate in candidates):
            return None, "CANDIDATE_KEY_MISMATCH"
        directions = {candidate.direction for candidate in candidates}
        with self.lock:
            self.locks = {
                lock_key: value for lock_key, value in self.locks.items()
                if lock_key[0] != key[0] or lock_key[1] == key[1]
            }
            if key in self.locks:
                return None, "CANDLE_LOCKED"
            if len(directions) != 1:
                return None, "CONTRADICTORY_DIRECTION"
            primary = candidates[0]
            matched_types = tuple(dict.fromkeys(candidate.signal_type for candidate in candidates))
            signal_type = "+".join(matched_types)
            accepted = replace(primary,
                               signal_type=signal_type,
                               matched_signal_types=matched_types,
                               signal_lock_status="ACCEPTED_LOCKED")
            self.locks[key] = accepted
            return accepted, "ACCEPTED" if len(matched_types) == 1 else "CONSOLIDATED"


class SignalCoordinator:
    def __init__(self, expiry_seconds=60):
        self.expiry = timedelta(seconds=expiry_seconds)
        self.pending = []
        self.active = {"PRIMARY": None, "SECONDARY": None}
        self.lock = threading.RLock()

    @staticmethod
    def slot(signal):
        return "PRIMARY" if signal.underlying in _PRIMARY else "SECONDARY"

    def submit(self, signal, now=None):
        now = now or datetime.now(signal.timestamp.tzinfo)
        with self.lock:
            slot = self.slot(signal)
            if self.active[slot] is None:
                self.active[slot] = {"signal": signal, "created_at": now, "status": "ACTIVE"}
                return "ACTIVE"
            self.pending.append({"signal": signal, "created_at": now, "status": "WAITING"})
            self.pending.sort(key=lambda item: (_PRIORITY.get(item["signal"].underlying, 99), item["created_at"], item["signal"].signal_id))
            return "WAITING"

    def resolve(self, signal_id, status):
        if status not in {"AUTO_ENTRY", "APPROVED", "REJECTED", "EXPIRED"}:
            raise ValueError("Invalid signal resolution")
        with self.lock:
            for slot, item in self.active.items():
                if item and item["signal"].signal_id == signal_id:
                    item["status"] = status
                    self.active[slot] = None
                    self._promote(slot)
                    return item
            for index, item in enumerate(self.pending):
                if item["signal"].signal_id == signal_id:
                    item["status"] = status
                    self.pending.pop(index)
                    return item
            return None

    def expire(self, now=None):
        now = now or datetime.now().astimezone()
        expired = []
        with self.lock:
            for slot, item in list(self.active.items()):
                if item and now - item["created_at"] >= self.expiry:
                    expired.append(self.resolve(item["signal"].signal_id, "EXPIRED"))
            remaining = []
            for item in self.pending:
                if now - item["created_at"] >= self.expiry:
                    item["status"] = "EXPIRED"
                    expired.append(item)
                else:
                    remaining.append(item)
            self.pending = remaining
        return expired

    def current(self, slot):
        with self.lock:
            return self.active[slot]

    def _promote(self, slot):
        for index, item in enumerate(self.pending):
            if self.slot(item["signal"]) == slot:
                item["status"] = "ACTIVE"
                self.active[slot] = item
                self.pending.pop(index)
                return


class ApprovalController:
    """Owns queued approval decisions in one thread."""

    def __init__(self, coordinator, on_decision):
        self.coordinator = coordinator
        self.on_decision = on_decision
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="approval-decisions", daemon=True)
        self.thread.start()

    def submit_key(self, key):
        self.commands.put(key.strip().upper())

    def stop(self):
        self.stop_event.set()
        self.commands.put("")

    def _run(self):
        while not self.stop_event.is_set():
            try:
                key = self.commands.get(timeout=0.5)
            except queue.Empty:
                for expired in self.coordinator.expire():
                    self.on_decision(expired)
                continue
            if not key or key[0] not in {"A", "R"}:
                continue
            self.process_key(key)

    def process_key(self, key):
        key = key.strip().upper()
        if not key or key[0] not in {"A", "R"}:
            return
        action = "APPROVED" if key[0] == "A" else "REJECTED"
        requested = key[1:]
        item = None
        active = [item for item in self.coordinator.active.values() if item]
        if requested.isdigit():
            index = int(requested) - 1
            if 0 <= index < len(active):
                item = active[index]
        elif len(active) == 1 and not self.coordinator.pending:
            item = active[0]
        if item:
            resolved = self.coordinator.resolve(item["signal"].signal_id, action)
            self.on_decision(resolved)


class KeyboardController:
    """Single terminal keyboard owner; never used by market-data callbacks."""

    def __init__(self, approval_controller, on_command=None):
        self.approval_controller = approval_controller
        self.on_command = on_command or (lambda command: None)
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if not sys.stdin.isatty():
            return
        self.thread = threading.Thread(target=self._run, name="terminal-keyboard", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        try:
            import msvcrt
        except ImportError:
            return
        buffer = ""
        while not self.stop_event.is_set():
            if not msvcrt.kbhit():
                self.stop_event.wait(0.05)
                continue
            character = msvcrt.getwch()
            if character in "\r\n":
                if buffer:
                    command = buffer.upper()
                    if command[0] in {"A", "R"}:
                        self.approval_controller.submit_key(command)
                    else:
                        self.on_command(f"UNKNOWN: {command}")
                    buffer = ""
                continue
            if character.isalnum():
                buffer += character
            elif character == "\x1b":
                buffer = ""
