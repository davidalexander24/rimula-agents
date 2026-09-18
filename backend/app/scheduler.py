"""[P2] Agent terjadwal dengan APScheduler (PRD §3.3 US-13, B-13). Pemilik: David (B).

Aktif hanya jika `SCHEDULER_ENABLED=true`. Default mati: retrain terjadwal di tengah demo akan mengubah versi model.
Semua job lewat `jobs.start_job(..., trigger="schedule")`, sehingga tercatat di tabel `jobs` dan `/agents/status`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from . import jobs, repo
from .errors import ApiError
from .state import AppState

log = logging.getLogger("formulapilot.scheduler")

DESIGNER_EVERY_MIN = 10
GUARDIAN_EVERY_MIN = 60
SCOUT_EVERY_HOURS = 24


class AgentScheduler:
    def __init__(self, state: AppState) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        self.state = state
        self._sched = BackgroundScheduler(timezone="Asia/Jakarta", job_defaults={"coalesce": True, "max_instances": 1})
        self._sched.add_job(self.tick_designer, "interval", minutes=DESIGNER_EVERY_MIN, id="designer")
        self._sched.add_job(self.tick_guardian, "interval", minutes=GUARDIAN_EVERY_MIN, id="guardian")
        self._sched.add_job(self.tick_scout, "interval", hours=SCOUT_EVERY_HOURS, id="scout")

    @property
    def running(self) -> bool:
        return bool(self._sched.running)

    def start(self) -> None:
        self._sched.start()
        log.info("scheduler aktif: designer %d mnt, guardian %d mnt, scout %d jam", DESIGNER_EVERY_MIN, GUARDIAN_EVERY_MIN, SCOUT_EVERY_HOURS)

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)

    def next_run(self, job_id: Optional[str] = None) -> Optional[datetime]:
        times = [j.next_run_time for j in self._sched.get_jobs() if j.next_run_time and (job_id is None or j.id == job_id)]
        return min(times) if times else None

    def _start(self, agent: str) -> Optional[str]:
        try:
            return jobs.start_job(self.state, agent, trigger="schedule").job_id
        except ApiError as exc:
            log.info("job terjadwal %s dilewati: %s", agent, exc.code)
            return None

    def has_untrained_results(self) -> bool:
        active = repo.active_model_version(self.state.db, "global")
        rows = repo.active_lab_rows(self.state.db, "global")
        if not rows:
            return False
        if active is None:
            return True
        return max(r["recorded_at"] for r in rows) > active["created_at"]

    def tick_designer(self) -> Optional[str]:
        if not self.has_untrained_results():
            return None
        return self._start("designer")

    def tick_guardian(self) -> Optional[str]:
        return self._start("guardian")

    def tick_scout(self) -> Optional[str]:
        return self._start("scout")
