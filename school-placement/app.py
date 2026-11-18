from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from model import SchoolPlacementModel, parse_capacity

app = Flask(__name__)
model = SchoolPlacementModel()
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


@app.errorhandler(Exception)
def handle_exception(exc: Exception):
    if request.path.startswith("/api/"):
        if isinstance(exc, HTTPException):
            return jsonify({"error": exc.description}), exc.code
        return jsonify({"error": str(exc)}), 500
    if isinstance(exc, HTTPException):
        return exc
    raise exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_auto_job(job_id: str, capacity: int) -> None:
    def progress(checked: int, total: int, block_id: int) -> None:
        with jobs_lock:
            job = jobs.get(job_id)
            if job is not None:
                job.update(
                    checked=checked,
                    total=total,
                    last_block_id=block_id,
                    updated_at=_now(),
                )

    def cancel() -> bool:
        with jobs_lock:
            job = jobs.get(job_id)
            return bool(job and job.get("cancel"))

    try:
        result = model.auto_search(capacity, progress=progress, cancel=cancel)
        with jobs_lock:
            job = jobs.get(job_id)
            if job is not None:
                job.update(result)
                if job.get("cancel"):
                    job["status"] = "cancelled"
                else:
                    job["status"] = "done" if result["complete"] else "partial"
                job["finished_at"] = _now()
                job["updated_at"] = job["finished_at"]
    except Exception as exc:
        with jobs_lock:
            job = jobs.get(job_id)
            if job is not None:
                job.update(
                    status="error",
                    error=str(exc),
                    finished_at=_now(),
                    updated_at=_now(),
                )


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/initial")
def initial():
    return jsonify(model.initial_payload())


@app.post("/api/scenario")
def scenario():
    payload = request.get_json(silent=True) or {}
    try:
        result = model.calculate_scenario(payload.get("placements", []))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/auto/start")
def auto_start():
    payload = request.get_json(silent=True) or {}
    try:
        capacity = parse_capacity(payload.get("capacity"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with jobs_lock:
        if any(job["status"] == "running" for job in jobs.values()):
            return jsonify({"error": "Автоматический подбор уже выполняется"}), 409
        job_id = uuid.uuid4().hex
        jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "capacity": capacity,
            "checked": 0,
            "total": len(model.block_ids),
            "last_block_id": None,
            "started_at": _now(),
            "updated_at": _now(),
            "cancel": False,
        }
    threading.Thread(
        target=_run_auto_job,
        args=(job_id, capacity),
        daemon=True,
        name=f"school-placement-auto-{job_id[:8]}",
    ).start()
    return jsonify({"job_id": job_id, "total": len(model.block_ids), "capacity": capacity}), 202


@app.get("/api/auto/status/<job_id>")
def auto_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Задача не найдена"}), 404
        return jsonify(job)


@app.post("/api/auto/cancel/<job_id>")
def auto_cancel(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Задача не найдена"}), 404
        if job["status"] != "running":
            return jsonify({"error": "Задача уже завершена"}), 409
        job["cancel"] = True
        job["updated_at"] = _now()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
