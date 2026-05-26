from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .schemas import DoctorResult
from .store import CORE_FILES


DEFAULT_MODEL_NAME = "fengerhu1/MobiMind-1.5-4B"


def _models_url(service_ip: str, model_port: int, model_base_url: str | None) -> str:
    if not model_base_url:
        return f"http://{service_ip}:{model_port}/v1/models"
    parsed = urllib.parse.urlsplit(model_base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = f"{path}/models"
    elif path.endswith("/v1/models"):
        path = path
    else:
        path = f"{path}/v1/models"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _check_models_endpoint(service_ip: str, model_port: int, model_name: str, model_base_url: str | None) -> dict[str, Any]:
    url = _models_url(service_ip, model_port, model_base_url)
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    models = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
    return {"ok": model_name in models, "url": url, "base_url": model_base_url, "models": models}


def _check_device() -> dict[str, Any]:
    adb = Path(__file__).resolve().parents[4] / "tools" / "platform-tools" / "adb.exe"
    program = str(adb) if adb.exists() else "adb"
    try:
        completed = subprocess.run([program, "devices"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    lines = [line for line in completed.stdout.splitlines() if "\tdevice" in line]
    return {"ok": completed.returncode == 0 and bool(lines), "stdout": completed.stdout, "device_count": len(lines)}


def run_doctor(
    *,
    artifacts_dir: Path,
    output_path: Path,
    service_ip: str,
    model_port: int,
    model_name: str = DEFAULT_MODEL_NAME,
    model_base_url: str | None = None,
    check_remote: bool = True,
    check_device: bool = True,
    env: dict[str, str] | None = None,
) -> DoctorResult:
    environment = env or os.environ
    checks: dict[str, dict[str, Any]] = {}
    missing = [name for name in CORE_FILES if not (artifacts_dir / name).exists()]
    checks["task2_artifacts"] = {"ok": not missing, "artifacts_dir": str(artifacts_dir), "missing": missing}
    expected = {
        "MOBIAGENT_DECIDER_MODEL": model_name,
        "MOBIAGENT_GROUNDER_MODEL": model_name,
        "MOBIAGENT_PLANNER_MODEL": model_name,
    }
    mismatches = {key: environment.get(key) for key, value in expected.items() if environment.get(key) != value}
    checks["single_model_env"] = {"ok": not mismatches, "expected": expected, "mismatches": mismatches}
    checks["remote_model"] = (
        _check_models_endpoint(service_ip, model_port, model_name, model_base_url)
        if check_remote
        else {"ok": True, "skipped": True, "base_url": model_base_url}
    )
    checks["device"] = _check_device() if check_device else {"ok": True, "skipped": True}
    ok = all(check.get("ok") for check in checks.values())
    result = DoctorResult(ok=ok, service_ip=service_ip, model_port=model_port, model_name=model_name, checks=checks)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result
