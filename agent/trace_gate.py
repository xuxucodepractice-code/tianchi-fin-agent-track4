"""Agent 推理追踪与盲标隔离基础设施。

本模块只记录和验证运行过程，不参与检索、Prompt 或答案决策。正式候选的
新推理必须留下完整 calls/derivations/manifest，并在候选冻结前通过验证。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import uuid
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agent.normalize_answer import normalize_answer, normalize_tf_verdict
from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT, bundle_paths
from agent.validate_submission import validate_submission_files

TRACE_SCHEMA_VERSION = "agent-trace/v1"
FREEZE_SCHEMA_VERSION = "candidate-freeze/v1"
LABEL_REVEAL_SCHEMA_VERSION = "label-reveal/v1"
OFFICIAL_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class BlindDataAccessError(PermissionError):
    """候选生成进程试图读取治理/盲标区。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def resolve_recorded_path(value: str, *, base: Path = REPO_ROOT) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


SELECTION_ALLOWED_KEYS = {
    "selection_id",
    "frozen_before_labeling",
    "selection_rule",
    "qids",
    "prospective_qids",
    "known_before_freeze_qids",
    "source_selection_path",
    "source_selection_sha256",
}


def load_frozen_selection(path: Path) -> dict[str, Any]:
    """读取无答案的预注册清单，并拒绝任何额外/标签字段。"""
    path = path.resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("selection must be a JSON object")
    unknown_keys = set(payload) - SELECTION_ALLOWED_KEYS
    if unknown_keys:
        raise ValueError(f"selection contains forbidden/unknown keys: {sorted(unknown_keys)}")
    if payload.get("frozen_before_labeling") is not True:
        raise ValueError("selection must declare frozen_before_labeling=true")
    qids = payload.get("qids")
    if (
        not isinstance(qids, list)
        or not qids
        or not all(isinstance(qid, str) and qid for qid in qids)
        or len(set(qids)) != len(qids)
    ):
        raise ValueError("selection qids must be a non-empty unique string list")
    prospective = payload.get("prospective_qids", qids)
    known = payload.get("known_before_freeze_qids", [])
    if not isinstance(prospective, list) or not isinstance(known, list):
        raise ValueError("prospective_qids/known_before_freeze_qids must be lists")
    prospective_set = set(map(str, prospective))
    known_set = set(map(str, known))
    if prospective_set & known_set or prospective_set | known_set != set(qids):
        raise ValueError(
            "prospective_qids and known_before_freeze_qids must be a disjoint partition of qids"
        )
    if len(prospective_set) != len(prospective) or len(known_set) != len(known):
        raise ValueError("selection prospective/known qids must be unique")
    return {
        **payload,
        "prospective_qids": [qid for qid in qids if qid in prospective_set],
        "known_before_freeze_qids": [qid for qid in qids if qid in known_set],
    }


def code_snapshot(code_root: Path | None = None) -> dict[str, Any]:
    """记录生成代码的逐文件 SHA256 与稳定树哈希。"""
    root = (code_root or (REPO_ROOT / "agent")).resolve()
    files = {
        str(path.relative_to(REPO_ROOT.resolve())): sha256_file(path)
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    return {
        "root": display_path(root),
        "files": files,
        "sha256": sha256_json(files),
    }


def input_artifact_snapshot(path: Path) -> dict[str, Any]:
    """记录候选输入文件或目录的稳定哈希；不复制内容。"""
    path = path.resolve()
    if path.is_file():
        return {
            "path": display_path(path),
            "kind": "file",
            "sha256": sha256_file(path),
        }
    if path.is_dir():
        files = {
            str(item.relative_to(path)): sha256_file(item)
            for item in sorted(path.rglob("*"))
            if item.is_file() and "__pycache__" not in item.parts
        }
        return {
            "path": display_path(path),
            "kind": "directory",
            "files": files,
            "sha256": sha256_json(files),
        }
    raise FileNotFoundError(f"input artifact missing: {path}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


_POLICY_LOCK = threading.RLock()
_ACTIVE_POLICY: tuple[
    tuple[Path, ...], tuple[Path, ...], tuple[Path, ...], bool, list[dict[str, str]]
] | None = None
_AUDIT_HOOK_INSTALLED = False


def _audit_open_hook(event: str, args: tuple[Any, ...]) -> None:
    with _POLICY_LOCK:
        policy = _ACTIVE_POLICY
    if policy is None:
        return
    forbidden_roots, allowed_roots, allowed_write_roots, block_subprocess, violations = policy
    def deny(message: str, *, path: Path | None = None) -> None:
        violation = {
            "event": event,
            "path": str(path) if path is not None else "",
            "detected_at": now_iso(),
            "message": message,
        }
        with _POLICY_LOCK:
            violations.append(violation)
        raise BlindDataAccessError(message)
    blocked_process_events = {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.fork",
        "os.forkpty",
        "pty.spawn",
        "_posixsubprocess.fork_exec",
    }
    if block_subprocess and (
        event in blocked_process_events
        or event.startswith("os.exec")
        or event.startswith("os.spawn")
    ):
        deny("candidate generation cannot spawn subprocesses")
    if block_subprocess and event in {
        "os.link",
        "os.symlink",
        "os.rename",
        "os.replace",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.chdir",
        "os.truncate",
    }:
        deny(
            "candidate generation cannot mutate filesystem topology while the blind guard is active"
        )
    if event == "os.mkdir":
        if not args:
            return
        raw_path = args[0]
        if isinstance(raw_path, int):
            return
        path = Path(os.fsdecode(raw_path)).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = path.resolve(strict=False)
        if not any(_is_within(resolved, root) for root in allowed_write_roots):
            deny(
                f"candidate generation write is outside the output allowlist: {resolved}",
                path=resolved,
            )
        return
    if event not in {"open", "os.listdir", "os.scandir"}:
        return
    if (not forbidden_roots and not allowed_roots) or not args:
        return
    raw_path = args[0]
    if isinstance(raw_path, int):
        return
    try:
        path = Path(os.fsdecode(raw_path)).expanduser()
    except (TypeError, ValueError):
        return
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve(strict=False)
    if event == "open":
        mode = args[1] if len(args) > 1 else "r"
        flags = args[2] if len(args) > 2 else None
        if isinstance(mode, str):
            reads_data = "r" in mode or "+" in mode
        elif isinstance(flags, int):
            reads_data = not bool(flags & os.O_WRONLY) or bool(flags & os.O_RDWR)
        else:
            reads_data = True
        writes_data = False
        if isinstance(mode, str):
            writes_data = any(flag in mode for flag in ("w", "a", "x", "+"))
        elif isinstance(flags, int):
            writes_data = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
        if writes_data and not any(
            _is_within(resolved, root) for root in allowed_write_roots
        ):
            deny(
                f"candidate generation write is outside the output allowlist: {resolved}",
                path=resolved,
            )
        if not reads_data:
            return
    if allowed_roots:
        if any(_is_within(resolved, root) for root in allowed_roots):
            return
        else:
            deny(
                f"candidate generation read is outside the process allowlist: {resolved}",
                path=resolved,
            )
    for root in forbidden_roots:
        if _is_within(resolved, root):
            deny(
                f"candidate generation cannot read governed blind-label data: {resolved}",
                path=resolved,
            )


def _ensure_audit_hook() -> None:
    global _AUDIT_HOOK_INSTALLED
    if not _AUDIT_HOOK_INSTALLED:
        sys.addaudithook(_audit_open_hook)
        _AUDIT_HOOK_INSTALLED = True


def default_candidate_forbidden_roots() -> tuple[Path, ...]:
    """显式列出最常见的标签、历史答案和旧推理泄漏源。"""
    return tuple(
        path.resolve()
        for path in (
            REPO_ROOT / "workspace" / "03_baseline_improvement",
            REPO_ROOT / "submission",
            REPO_ROOT / "outputs" / "candidates",
            REPO_ROOT / "outputs" / "experiments",
            REPO_ROOT / "processed_data" / "reasoning_samples",
            REPO_ROOT / "tests",
            REPO_ROOT / ".git",
        )
    )


def default_runtime_read_roots() -> tuple[Path, ...]:
    """候选联网所需、且不应承载实验数据的解释器/系统只读根。"""
    candidates = (
        Path(sys.prefix),
        Path("/etc"),
        Path("/private/etc"),
        Path("/System/Library"),
        Path("/Library/Keychains"),
        Path("/usr/share/zoneinfo"),
        Path("/dev"),
    )
    roots: list[Path] = []
    for path in candidates:
        if path.exists():
            resolved = path.resolve()
            if resolved not in roots:
                roots.append(resolved)
    return tuple(roots)


def active_guard_policy_snapshot() -> dict[str, Any]:
    """返回实际生效的进程级 policy；没有 guard 时 fail closed。"""
    with _POLICY_LOCK:
        policy = _ACTIVE_POLICY
    if policy is None:
        raise BlindDataAccessError(
            "Agent Trace Recorder requires an active process-wide blind_data_guard"
        )
    forbidden, allowed, allowed_write, block_subprocess, _ = policy
    payload = {
        "enforced": True,
        "forbidden_roots": [display_path(path) for path in forbidden],
        "allowed_read_roots": [display_path(path) for path in allowed],
        "allowed_write_roots": [display_path(path) for path in allowed_write],
        "subprocess_blocked": block_subprocess,
        "scope": "process_wide_including_threads",
    }
    return {**payload, "policy_sha256": sha256_json(payload)}


@contextmanager
def blind_data_guard(
    forbidden_roots: tuple[Path, ...] | None = None,
    *,
    allowed_read_roots: tuple[Path, ...] = (),
    allowed_write_roots: tuple[Path, ...] = (),
    block_subprocess: bool = True,
) -> Iterator[tuple[Path, ...]]:
    """进程级 fail-closed guard；活动期间禁止嵌套或并发换策略扩权。"""
    _ensure_audit_hook()
    roots = tuple(
        path.expanduser().resolve()
        for path in (forbidden_roots or default_candidate_forbidden_roots())
    )
    allowed = tuple(
        dict.fromkeys(
            [
                *(path.expanduser().resolve() for path in allowed_read_roots),
                *default_runtime_read_roots(),
            ]
        )
    )
    allowed_write = tuple(path.expanduser().resolve() for path in allowed_write_roots)
    violations: list[dict[str, str]] = []
    global _ACTIVE_POLICY
    with _POLICY_LOCK:
        if _ACTIVE_POLICY is not None:
            violation = {
                "event": "blind_data_guard.nested_policy",
                "path": "",
                "detected_at": now_iso(),
                "message": "cannot replace an active process-wide blind-data policy",
            }
            _ACTIVE_POLICY[4].append(violation)
            raise BlindDataAccessError(violation["message"])
        policy = (roots, allowed, allowed_write, block_subprocess, violations)
        _ACTIVE_POLICY = policy
    try:
        yield roots
    finally:
        with _POLICY_LOCK:
            if _ACTIVE_POLICY is policy:
                _ACTIVE_POLICY = None
            else:
                violations.append(
                    {
                        "event": "blind_data_guard.policy_replaced",
                        "path": "",
                        "detected_at": now_iso(),
                        "message": "active blind-data policy changed unexpectedly",
                    }
                )
                _ACTIVE_POLICY = None


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{lineno}: expected JSON object")
        records.append(value)
    return records


def _read_bundle_for_partition(
    bundle_dir: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]], dict[str, Any]]:
    answer_path, evidence_path, manifest_path = bundle_paths(bundle_dir)
    with answer_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or rows[0].get("qid") != "summary":
        raise ValueError(f"answer.csv missing summary row: {answer_path}")
    answers: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        qid = str(row.get("qid", ""))
        if not qid or qid in answers:
            raise ValueError(f"answer.csv contains invalid/duplicate qid: {qid!r}")
        answers[qid] = row
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence_payload, list):
        raise ValueError("evidence.json must be a list")
    evidence: dict[str, dict[str, Any]] = {}
    for record in evidence_payload:
        if not isinstance(record, dict):
            raise ValueError("evidence.json contains a non-object record")
        qid = str(record.get("qid", ""))
        if not qid or qid in evidence:
            raise ValueError(f"evidence.json contains invalid/duplicate qid: {qid!r}")
        evidence[qid] = record
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("run_manifest.json must be an object")
    return answers, evidence, manifest


def _validate_candidate_parent_partition(
    candidate_dir: Path,
    parent_dir: Path,
    *,
    traced_qids: list[str],
    selection: dict[str, Any],
    trace_run_id: str,
    parent_version: str,
) -> list[str]:
    """证明新答案仅来自 traced qids，其余记录逐字段继承冻结父版本。"""
    errors: list[str] = []
    try:
        official_qids = [str(item["qid"]) for item in load_all_questions()]
        official_set = set(official_qids)
        candidate_answers, candidate_evidence, manifest = _read_bundle_for_partition(
            candidate_dir
        )
        parent_answers, parent_evidence, _ = _read_bundle_for_partition(parent_dir)
        if list(candidate_answers) != official_qids:
            errors.append("candidate answer qids/order differ from the official question set")
        if list(candidate_evidence) != official_qids:
            errors.append("candidate evidence qids/order differ from the official question set")
        if set(parent_answers) != official_set or set(parent_evidence) != official_set:
            errors.append("parent qids differ from the official question set")
        if len(traced_qids) != len(set(traced_qids)) or not set(traced_qids) <= official_set:
            errors.append("traced qids are duplicate or outside the official question set")
        inherited_qids = [qid for qid in official_qids if qid not in set(traced_qids)]
        if inherited_qids:
            if resolve_recorded_path(str(manifest.get("parent_artifact_dir", ""))) != (
                parent_dir.resolve()
            ):
                errors.append("candidate manifest parent directory differs from freeze parent")
            if str(manifest.get("parent_version", "")) != parent_version:
                errors.append("candidate manifest parent_version differs from freeze parent")
            expected_parent_hashes = manifest.get("parent_artifact_sha256") or {}
            actual_parent_hashes = {
                "answer_csv": sha256_file(parent_dir / "answer.csv"),
                "evidence_json": sha256_file(parent_dir / "evidence.json"),
                "run_manifest_json": sha256_file(parent_dir / "run_manifest.json"),
            }
            if expected_parent_hashes != actual_parent_hashes:
                errors.append("candidate manifest parent hashes differ from freeze parent")
        for qid in inherited_qids:
            if candidate_answers.get(qid) != parent_answers.get(qid):
                errors.append(f"untraced answer differs from frozen parent: {qid}")
            if candidate_evidence.get(qid) != parent_evidence.get(qid):
                errors.append(f"untraced evidence differs from frozen parent: {qid}")

        if [str(value) for value in manifest.get("qids", [])] != official_qids:
            errors.append("candidate manifest qids/order differ from the official question set")
        if set(map(str, manifest.get("rerun_qids", []))) != set(traced_qids):
            errors.append("candidate manifest rerun_qids differ from traced qids")
        gate = manifest.get("agent_trace_gate") or {}
        if gate.get("status") != "PASS":
            errors.append("candidate manifest agent_trace_gate is not PASS")
        if str(gate.get("trace_run_id", "")) != trace_run_id:
            errors.append("candidate manifest trace_run_id differs from frozen trace")
        if [str(value) for value in gate.get("fresh_traced_qids", [])] != traced_qids:
            errors.append("candidate fresh_traced_qids differ from trace order")
        if [str(value) for value in gate.get("legacy_inherited_qids", [])] != inherited_qids:
            errors.append("candidate inherited qids do not complement traced qids")
        if [str(value) for value in gate.get("prospective_qids", [])] != [
            str(value) for value in selection["prospective_qids"]
        ]:
            errors.append("candidate prospective qids differ from frozen selection")
        if [str(value) for value in gate.get("known_before_freeze_qids", [])] != [
            str(value) for value in selection["known_before_freeze_qids"]
        ]:
            errors.append("candidate known-before-freeze qids differ from selection")
        lineage = manifest.get("per_record_lineage") or {}
        if not isinstance(lineage, dict) or set(lineage) != official_set:
            errors.append("candidate per_record_lineage does not cover the official qids")
        else:
            for qid in official_qids:
                expected_kind = "rerun" if qid in set(traced_qids) else "parent"
                if str((lineage.get(qid) or {}).get("source_kind", "")) != expected_kind:
                    errors.append(f"candidate lineage source_kind mismatch: {qid}")
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        errors.append(f"unable to validate candidate/parent partition: {exc}")
    return errors


class AgentTraceRecorder:
    """逐次落盘 API 调用与答案派生，崩溃时仍保留已完成记录。"""

    def __init__(
        self,
        trace_dir: Path,
        *,
        purpose: str,
        model: str,
        base_url: str,
        config: dict[str, Any],
        run_id: str | None = None,
    ) -> None:
        guard_policy = active_guard_policy_snapshot()
        with _POLICY_LOCK:
            policy = _ACTIVE_POLICY
        if policy is None:
            raise BlindDataAccessError("blind-data guard disappeared during recorder setup")
        self._guard_violations = policy[4]
        if self._guard_violations:
            raise BlindDataAccessError("blind-data guard already recorded an access violation")
        self.trace_dir = trace_dir.resolve()
        self.trace_dir.mkdir(parents=True, exist_ok=False)
        self.calls_path = self.trace_dir / "calls.jsonl"
        self.derivations_path = self.trace_dir / "derivations.jsonl"
        self.manifest_path = self.trace_dir / "trace_manifest.json"
        self.calls_path.touch()
        self.derivations_path.touch()
        self.run_id = run_id or f"trace-{uuid.uuid4()}"
        self.call_count = 0
        self.successful_call_count = 0
        self.failed_call_count = 0
        self.derivation_count = 0
        model_identity = {
            "provider": "dashscope-openai-compatible",
            "model": model,
            "base_url": base_url,
        }
        self.manifest: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_run_id": self.run_id,
            "purpose": purpose,
            "candidate_eligible": purpose == "candidate_generation",
            "status": "recording",
            "started_at": now_iso(),
            "finished_at": None,
            "code": code_snapshot(),
            "config": config,
            "config_sha256": sha256_json(config),
            "model": model_identity,
            "model_sha256": sha256_json(model_identity),
            "blind_data_guard": guard_policy,
            "trace_files": {
                "calls": "calls.jsonl",
                "derivations": "derivations.jsonl",
            },
            "call_count": 0,
            "successful_call_count": 0,
            "failed_call_count": 0,
            "derivation_count": 0,
            "output_artifacts": {},
        }
        self._write_manifest()

    def assert_guard_active(self) -> None:
        if self._guard_violations:
            raise BlindDataAccessError(
                "blind-data guard recorded a prior access violation; trace is ineligible"
            )
        current = active_guard_policy_snapshot()
        expected = (self.manifest.get("blind_data_guard") or {}).get("policy_sha256")
        if current.get("policy_sha256") != expected:
            raise BlindDataAccessError(
                "blind-data guard changed or was disabled during a traced API run"
            )

    def _write_manifest(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def new_call_id(self) -> str:
        return f"call-{uuid.uuid4()}"

    def record_call(self, record: dict[str, Any]) -> None:
        entry = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_run_id": self.run_id,
            **record,
        }
        _append_jsonl(self.calls_path, entry)
        self.call_count += 1
        if entry.get("status") == "success":
            self.successful_call_count += 1
        else:
            self.failed_call_count += 1

    def record_derivation(self, result: dict[str, Any]) -> None:
        option_judgments = result.get("option_judgments", {})
        call_ids: list[str] = []
        for option_key in sorted(option_judgments):
            judgment = option_judgments[option_key]
            value = judgment.get("trace_call_id") if isinstance(judgment, dict) else None
            if value and str(value) not in call_ids:
                call_ids.append(str(value))
        tf_judgment = result.get("tf_judgment")
        if isinstance(tf_judgment, dict):
            call_ids.extend(
                str(value)
                for value in tf_judgment.get("trace_call_ids", [])
                if value and str(value) not in call_ids
            )
        entry = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_run_id": self.run_id,
            "qid": str(result.get("qid", "")),
            "derivation_id": f"derivation-{uuid.uuid4()}",
            "stage": str(result.get("_trace_derivation_stage", "candidate_answer")),
            "recorded_at": now_iso(),
            "source_kind": (
                "reused_cache" if result.get("_reused_from_cache") else "fresh_inference"
            ),
            "trace_call_ids": call_ids,
            "answer_format": result.get("answer_format"),
            "answer": result.get("answer"),
            "answer_derivation": result.get("answer_derivation", {}),
            "retrieval_sha256": sha256_json(result.get("retrieval", {})),
            "prompt_tokens": int(result.get("prompt_tokens") or 0),
            "completion_tokens": int(result.get("completion_tokens") or 0),
            "total_tokens": int(result.get("total_tokens") or 0),
        }
        _append_jsonl(self.derivations_path, entry)
        self.derivation_count += 1

    def finalize(
        self,
        *,
        output_paths: tuple[Path, ...] | None,
        failures: list[dict[str, str]],
    ) -> Path:
        artifacts: dict[str, dict[str, str]] = {}
        if output_paths is not None:
            for path in output_paths:
                if path.is_file():
                    artifacts[path.name] = {
                        "path": display_path(path),
                        "sha256": sha256_file(path),
                    }
        calls = _read_jsonl(self.calls_path)
        end_code = code_snapshot()
        code_unchanged = end_code.get("sha256") == (self.manifest.get("code") or {}).get(
            "sha256"
        )
        served_models = sorted(
            {
                str(call.get("response_model"))
                for call in calls
                if call.get("response_model")
            }
        )
        self.manifest.update(
            {
                "status": (
                    "completed"
                    if not failures
                    and not self.failed_call_count
                    and not self._guard_violations
                    and code_unchanged
                    else "failed"
                ),
                "finished_at": now_iso(),
                "call_count": self.call_count,
                "successful_call_count": self.successful_call_count,
                "failed_call_count": self.failed_call_count,
                "derivation_count": self.derivation_count,
                "failures": failures,
                "guard_violations": list(self._guard_violations),
                "code_at_finish": end_code,
                "code_unchanged_during_run": code_unchanged,
                "served_models": served_models,
                "output_artifacts": artifacts,
                "trace_files_sha256": {
                    "calls.jsonl": sha256_file(self.calls_path),
                    "derivations.jsonl": sha256_file(self.derivations_path),
                },
            }
        )
        self._write_manifest()
        return self.manifest_path


def validate_trace_directory(
    trace_dir: Path,
    *,
    artifact_dir: Path | None = None,
    require_candidate_eligible: bool = True,
    require_current_code_match: bool = False,
    allow_frozen_relocation: bool = False,
) -> dict[str, Any]:
    """验证 trace 完整性；任何缺项都 fail closed。"""
    trace_dir = trace_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = trace_dir / "trace_manifest.json"
    calls_path = trace_dir / "calls.jsonl"
    derivations_path = trace_dir / "derivations.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        calls = _read_jsonl(calls_path)
        derivations = _read_jsonl(derivations_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"unable to load trace: {exc}"], "warnings": []}

    if manifest.get("schema_version") != TRACE_SCHEMA_VERSION:
        errors.append("trace schema_version mismatch")
    if manifest.get("status") != "completed":
        errors.append(f"trace status is not completed: {manifest.get('status')!r}")
    if require_candidate_eligible and manifest.get("candidate_eligible") is not True:
        errors.append("trace purpose is not candidate eligible")
    if require_candidate_eligible and (manifest.get("config") or {}).get("runner") != "agent.run_submission":
        errors.append("candidate trace did not use the governed agent.run_submission runner")
    guard = manifest.get("blind_data_guard") or {}
    if require_candidate_eligible and guard.get("enforced") is not True:
        errors.append("blind-data guard was not enforced")
    if require_candidate_eligible and not guard.get("allowed_read_roots"):
        errors.append("repository read allowlist was not recorded")
    if require_candidate_eligible and guard.get("subprocess_blocked") is not True:
        errors.append("subprocess execution was not blocked")
    policy_payload = {
        key: guard.get(key)
        for key in (
            "enforced",
            "forbidden_roots",
            "allowed_read_roots",
            "allowed_write_roots",
            "subprocess_blocked",
            "scope",
        )
    }
    if sha256_json(policy_payload) != guard.get("policy_sha256"):
        errors.append("blind-data guard policy hash mismatch")
    if manifest.get("guard_violations"):
        errors.append("blind-data guard recorded access violations")
    allowed_read: list[Path] = []
    allowed_write: list[Path] = []
    if require_candidate_eligible:
        mandated_roots = default_candidate_forbidden_roots()
        mandated = {display_path(path) for path in mandated_roots}
        recorded_forbidden = set(map(str, guard.get("forbidden_roots") or []))
        if mandated != recorded_forbidden:
            errors.append("blind-data guard forbidden roots differ from governed policy")
        allowed_read = [resolve_recorded_path(str(value)) for value in guard.get("allowed_read_roots") or []]
        allowed_write = [resolve_recorded_path(str(value)) for value in guard.get("allowed_write_roots") or []]
        if any(path == REPO_ROOT.resolve() for path in allowed_read + allowed_write):
            errors.append("blind-data guard allowlist is broader than permitted")
        if not allowed_write:
            errors.append("blind-data guard write allowlist is missing")
        config = manifest.get("config") or {}
        selection_value = config.get("selection_file")
        selection_hash = config.get("selection_sha256")
        selection_path: Path | None = None
        if not selection_value or not selection_hash:
            errors.append("candidate trace lacks a frozen blind selection")
        else:
            selection_path = resolve_recorded_path(str(selection_value))
            if selection_path not in allowed_read:
                errors.append("frozen blind selection was not the exact allowed input file")
            elif not selection_path.is_file() or sha256_file(selection_path) != selection_hash:
                errors.append("frozen blind selection hash mismatch")
            else:
                try:
                    selection_payload = load_frozen_selection(selection_path)
                    if [str(value) for value in config.get("qids", [])] != [
                        str(value) for value in selection_payload["qids"]
                    ]:
                        errors.append("trace qids differ from frozen blind selection")
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"invalid frozen blind selection: {exc}")
        output_value = config.get("output_dir")
        output_path: Path | None = None
        if output_value:
            output_path = resolve_recorded_path(str(output_value))
            if output_path not in allowed_write:
                errors.append("trace output directory differs from write allowlist")
            governed_output_root = (REPO_ROOT / "outputs" / "experiments").resolve()
            if output_path == governed_output_root or not _is_within(
                output_path, governed_output_root
            ):
                errors.append("candidate trace output is outside outputs/experiments")
            if not allow_frozen_relocation and not _is_within(trace_dir, output_path):
                errors.append("agent trace directory is outside the trace output directory")
            cache_value = config.get("reasoning_samples_dir")
            if cache_value and not _is_within(
                resolve_recorded_path(str(cache_value)), output_path
            ):
                errors.append("reasoning cache is outside the trace output directory")
        else:
            errors.append("candidate trace output directory is missing")
        if output_path is not None and set(allowed_write) != {output_path}:
            errors.append("blind-data write allowlist is not exactly the trace output directory")
        if selection_path is not None and output_path is not None:
            expected_read = {
                (REPO_ROOT / "agent").resolve(),
                (
                    REPO_ROOT
                    / "public_dataset_upload"
                    / "questions"
                    / "group_a"
                ).resolve(),
                (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
                (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
                selection_path,
                output_path,
            }
            if bool(config.get("hide_doc_ids")):
                expected_read.add(
                    (REPO_ROOT / "processed_data" / "doc_cards.json").resolve()
                )
            expected_read.update(default_runtime_read_roots())
            if set(allowed_read) != expected_read:
                errors.append("blind-data read allowlist differs from governed runner inputs")
        for path in allowed_read:
            if not any(_is_within(path, root) for root in mandated_roots):
                continue
            is_selection = selection_path is not None and path == selection_path
            is_own_output = output_path is not None and _is_within(path, output_path)
            if not is_selection and not is_own_output:
                errors.append(
                    "blind-data read allowlist exposes a governed forbidden path: "
                    f"{display_path(path)}"
                )
    if sha256_json(manifest.get("config", {})) != manifest.get("config_sha256"):
        errors.append("config hash mismatch")
    if sha256_json(manifest.get("model", {})) != manifest.get("model_sha256"):
        errors.append("model hash mismatch")
    model_identity = manifest.get("model") or {}
    if require_candidate_eligible:
        if model_identity.get("provider") != "dashscope-openai-compatible":
            errors.append("candidate trace provider is not DashScope")
        if str(model_identity.get("base_url", "")).rstrip("/") != (
            OFFICIAL_DASHSCOPE_BASE_URL
        ):
            errors.append("candidate trace base_url is not the official DashScope endpoint")
        if not str(model_identity.get("model", "")).startswith("qwen-"):
            errors.append("candidate trace requested model is not a Qwen model")
    input_artifacts = (manifest.get("config") or {}).get("input_artifacts") or {}
    if not isinstance(input_artifacts, dict):
        errors.append("input_artifacts must be an object")
        input_artifacts = {}
    if require_candidate_eligible and not {
        "questions",
        "chunks",
        "doc_meta",
    } <= set(input_artifacts):
        errors.append("candidate trace input artifact inventory is incomplete")
    for name, entry in input_artifacts.items():
        if not isinstance(entry, dict):
            errors.append(f"input artifact metadata is invalid: {name}")
            continue
        kind = str(entry.get("kind", ""))
        if kind == "directory":
            if not isinstance(entry.get("files"), dict) or sha256_json(
                entry.get("files") or {}
            ) != entry.get("sha256"):
                errors.append(f"input artifact tree hash mismatch: {name}")
        elif kind != "file" or not str(entry.get("sha256", "")):
            errors.append(f"input artifact file metadata is invalid: {name}")
        artifact_path = resolve_recorded_path(str(entry.get("path", "")))
        if require_candidate_eligible and not any(
            _is_within(artifact_path, root) for root in allowed_read
        ):
            errors.append(f"input artifact is outside the read allowlist: {name}")
        if require_current_code_match:
            try:
                current = input_artifact_snapshot(artifact_path)
                if current.get("kind") != kind or current.get("sha256") != entry.get(
                    "sha256"
                ):
                    errors.append(f"current input artifact differs from trace: {name}")
            except (OSError, ValueError) as exc:
                errors.append(f"unable to verify current input artifact {name}: {exc}")
    code = manifest.get("code") or {}
    if sha256_json(code.get("files", {})) != code.get("sha256"):
        errors.append("stored code snapshot hash mismatch")
    if manifest.get("code_unchanged_during_run") is not True:
        errors.append("generation code changed during the traced run")
    end_code = manifest.get("code_at_finish") or {}
    if end_code.get("sha256") != code.get("sha256"):
        errors.append("start/end code snapshots differ")
    if require_current_code_match and code_snapshot().get("sha256") != code.get("sha256"):
        errors.append("current generation code differs from traced code snapshot")
    for name, entry in (manifest.get("output_artifacts") or {}).items():
        path = resolve_recorded_path(str((entry or {}).get("path", "")))
        if not path.exists():
            warnings.append(f"recorded source artifact is no longer present: {name}")
        elif not path.is_file() or sha256_file(path) != (entry or {}).get("sha256"):
            errors.append(f"recorded source artifact hash mismatch: {name}")
    expected_trace_hashes = manifest.get("trace_files_sha256") or {}
    for path in (calls_path, derivations_path):
        if path.is_file() and expected_trace_hashes.get(path.name) != sha256_file(path):
            errors.append(f"trace file hash mismatch: {path.name}")

    if int(manifest.get("call_count") or 0) != len(calls):
        errors.append("call_count does not match calls.jsonl")
    if int(manifest.get("derivation_count") or 0) != len(derivations):
        errors.append("derivation_count does not match derivations.jsonl")
    successful_calls = sum(call.get("status") == "success" for call in calls)
    failed_calls = len(calls) - successful_calls
    if int(manifest.get("successful_call_count") or 0) != successful_calls:
        errors.append("successful_call_count mismatch")
    if int(manifest.get("failed_call_count") or 0) != failed_calls:
        errors.append("failed_call_count mismatch")
    trace_run_id = str(manifest.get("trace_run_id", ""))
    if not trace_run_id:
        errors.append("trace_run_id is missing")

    def parse_trace_time(value: Any, *, label: str) -> datetime | None:
        try:
            return parse_aware_datetime(str(value or ""), field=label)
        except ValueError as exc:
            errors.append(str(exc))
            return None

    trace_started_at = parse_trace_time(
        manifest.get("started_at"), label="trace.started_at"
    )
    trace_finished_at = parse_trace_time(
        manifest.get("finished_at"), label="trace.finished_at"
    )
    if (
        trace_started_at is not None
        and trace_finished_at is not None
        and trace_started_at > trace_finished_at
    ):
        errors.append("trace.started_at is later than trace.finished_at")
    known_call_ids: set[str] = set()
    for index, call in enumerate(calls, start=1):
        prefix = f"call[{index}]"
        if str(call.get("trace_run_id", "")) != trace_run_id:
            errors.append(f"{prefix}: trace_run_id mismatch")
        call_id = str(call.get("call_id", ""))
        if not call_id or call_id in known_call_ids:
            errors.append(f"{prefix}: missing or duplicate call_id")
        known_call_ids.add(call_id)
        if call.get("status") != "success":
            errors.append(f"{prefix}: call did not succeed")
        call_started_at = parse_trace_time(
            call.get("started_at"), label=f"{prefix}.started_at"
        )
        call_finished_at = parse_trace_time(
            call.get("finished_at"), label=f"{prefix}.finished_at"
        )
        if (
            call_started_at is not None
            and call_finished_at is not None
            and call_started_at > call_finished_at
        ):
            errors.append(f"{prefix}: started_at is later than finished_at")
        if (
            trace_started_at is not None
            and call_started_at is not None
            and call_started_at < trace_started_at
        ) or (
            trace_finished_at is not None
            and call_finished_at is not None
            and call_finished_at > trace_finished_at
        ):
            errors.append(f"{prefix}: call timestamps fall outside the trace window")
        messages = call.get("messages")
        evidence = call.get("model_evidence")
        raw_response = call.get("raw_response")
        if not isinstance(messages, list) or not messages:
            errors.append(f"{prefix}: full messages missing")
        elif sha256_json(messages) != call.get("messages_sha256"):
            errors.append(f"{prefix}: messages hash mismatch")
        if not isinstance(evidence, list):
            errors.append(f"{prefix}: model_evidence must be a list")
        elif sha256_json(evidence) != call.get("model_evidence_sha256"):
            errors.append(f"{prefix}: model_evidence hash mismatch")
        request_payload = call.get("request_payload")
        if not isinstance(request_payload, dict):
            errors.append(f"{prefix}: request_payload missing")
        elif sha256_json(request_payload) != call.get("request_payload_sha256"):
            errors.append(f"{prefix}: request payload hash mismatch")
        elif request_payload.get("messages") != messages:
            errors.append(f"{prefix}: request payload messages differ from recorded messages")
        if not isinstance(raw_response, dict):
            errors.append(f"{prefix}: raw_response missing")
        elif sha256_json(raw_response) != call.get("raw_response_sha256"):
            errors.append(f"{prefix}: raw response hash mismatch")
        else:
            choices = raw_response.get("choices")
            first_choice = (
                choices[0]
                if isinstance(choices, list) and choices and isinstance(choices[0], dict)
                else {}
            )
            message = first_choice.get("message") if isinstance(first_choice, dict) else {}
            message = message if isinstance(message, dict) else {}
            if message.get("content") != call.get("response_content"):
                errors.append(f"{prefix}: response content differs from raw response")
            raw_tools = message.get("tool_calls") or []
            if raw_tools != call.get("tool_calls"):
                errors.append(f"{prefix}: tool_calls differ from raw response")
            if first_choice.get("finish_reason", "") != call.get("finish_reason", ""):
                errors.append(f"{prefix}: finish_reason differs from raw response")
            provider_id = str(raw_response.get("id") or raw_response.get("request_id") or "")
            if provider_id != str(call.get("provider_request_id", "")):
                errors.append(f"{prefix}: provider request id differs from raw response")
            if str(raw_response.get("model") or call.get("response_model") or "") != str(
                call.get("response_model") or ""
            ):
                errors.append(f"{prefix}: served model differs from raw response")
        if not call.get("local_request_id"):
            errors.append(f"{prefix}: local_request_id missing")
        if require_candidate_eligible and not call.get("provider_request_id"):
            errors.append(f"{prefix}: provider_request_id missing")
        if require_candidate_eligible and not str(call.get("response_model", "")).startswith(
            "qwen-"
        ):
            errors.append(f"{prefix}: served model is not a Qwen model")
        attempts = call.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            errors.append(f"{prefix}: retry attempts missing")
        elif int(call.get("retry_count") or 0) != max(0, len(attempts) - 1):
            errors.append(f"{prefix}: retry_count mismatch")
        else:
            previous_finished: datetime | None = None
            for attempt_index, attempt in enumerate(attempts, start=1):
                if not isinstance(attempt, dict):
                    errors.append(f"{prefix}: attempt[{attempt_index}] is not an object")
                    continue
                attempt_started = parse_trace_time(
                    attempt.get("started_at"),
                    label=f"{prefix}.attempt[{attempt_index}].started_at",
                )
                attempt_finished = parse_trace_time(
                    attempt.get("finished_at"),
                    label=f"{prefix}.attempt[{attempt_index}].finished_at",
                )
                if (
                    attempt_started is not None
                    and attempt_finished is not None
                    and attempt_started > attempt_finished
                ):
                    errors.append(
                        f"{prefix}: attempt[{attempt_index}] has reversed timestamps"
                    )
                if (
                    call_started_at is not None
                    and attempt_started is not None
                    and attempt_started < call_started_at
                ) or (
                    call_finished_at is not None
                    and attempt_finished is not None
                    and attempt_finished > call_finished_at
                ):
                    errors.append(
                        f"{prefix}: attempt[{attempt_index}] falls outside call window"
                    )
                if (
                    previous_finished is not None
                    and attempt_started is not None
                    and attempt_started < previous_finished
                ):
                    errors.append(f"{prefix}: retry attempts overlap or move backward")
                previous_finished = attempt_finished or previous_finished
        if not isinstance(call.get("tool_calls"), list):
            errors.append(f"{prefix}: tool_calls must be a list")
        elif require_candidate_eligible and call.get("tool_calls"):
            errors.append(f"{prefix}: candidate inference must not contain tool calls")
        if require_candidate_eligible and str(call.get("finish_reason", "")) != "stop":
            errors.append(f"{prefix}: candidate inference finish_reason must be stop")
        usage = call.get("usage") or {}
        if int(usage.get("total_tokens") or 0) <= 0:
            errors.append(f"{prefix}: total_tokens must be positive")
        raw_usage = raw_response.get("usage") if isinstance(raw_response, dict) else {}
        raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
        expected_prompt = int(raw_usage.get("prompt_tokens") or 0)
        expected_completion = int(raw_usage.get("completion_tokens") or 0)
        expected_total = int(
            raw_usage.get("total_tokens") or expected_prompt + expected_completion
        )
        if (
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
            int(usage.get("total_tokens") or 0),
        ) != (expected_prompt, expected_completion, expected_total):
            errors.append(f"{prefix}: usage differs from raw response")
        joined_messages = "\n".join(
            str(message.get("content", ""))
            for message in messages or []
            if isinstance(message, dict)
        )
        for evidence_index, item in enumerate(evidence or [], start=1):
            if isinstance(item, dict) and str(item.get("text", "")) not in joined_messages:
                errors.append(
                    f"{prefix}: evidence[{evidence_index}] text is absent from exact messages"
                )

    seen_qids: set[str] = set()
    from agent.reason_qwen import extract_json_from_text

    claimed_call_counts: dict[str, int] = {}
    for derivation_record in derivations:
        for value in derivation_record.get("trace_call_ids") or []:
            call_id = str(value)
            claimed_call_counts[call_id] = claimed_call_counts.get(call_id, 0) + 1
    if require_candidate_eligible:
        duplicate_claims = sorted(
            call_id for call_id, count in claimed_call_counts.items() if count != 1
        )
        if duplicate_claims:
            errors.append(
                f"candidate call IDs must belong to exactly one derivation: {duplicate_claims}"
            )

    for index, item in enumerate(derivations, start=1):
        prefix = f"derivation[{index}]"
        if str(item.get("trace_run_id", "")) != trace_run_id:
            errors.append(f"{prefix}: trace_run_id mismatch")
        recorded_at = parse_trace_time(
            item.get("recorded_at"), label=f"{prefix}.recorded_at"
        )
        if (
            trace_started_at is not None
            and recorded_at is not None
            and recorded_at < trace_started_at
        ) or (
            trace_finished_at is not None
            and recorded_at is not None
            and recorded_at > trace_finished_at
        ):
            errors.append(f"{prefix}: recorded_at falls outside the trace window")
        qid = str(item.get("qid", ""))
        if not qid or (require_candidate_eligible and qid in seen_qids):
            errors.append(f"{prefix}: missing or duplicate candidate qid")
        seen_qids.add(qid)
        if item.get("source_kind") != "fresh_inference":
            errors.append(f"{prefix}: untraced cache reuse is not candidate eligible")
        call_ids = item.get("trace_call_ids")
        if not isinstance(call_ids, list) or not call_ids:
            errors.append(f"{prefix}: trace_call_ids missing")
        else:
            if len(call_ids) != len(set(map(str, call_ids))):
                errors.append(f"{prefix}: trace_call_ids contain duplicates")
            unknown = set(map(str, call_ids)) - known_call_ids
            if unknown:
                errors.append(f"{prefix}: unknown trace_call_ids {sorted(unknown)}")
        derivation = item.get("answer_derivation")
        if not isinstance(derivation, dict) or not derivation.get("method"):
            errors.append(f"{prefix}: answer derivation missing")
        elif str(derivation.get("output_answer", "")) != str(item.get("answer", "")):
            errors.append(f"{prefix}: derivation output does not match answer")
        else:
            try:
                method = str(derivation.get("method", ""))
                if method == "agent.normalize_answer.normalize_answer":
                    input_judgments = derivation.get("input_judgments") or {}
                    if require_candidate_eligible and any(
                        value.get("judgment") == "error" or bool(value.get("error"))
                        for value in input_judgments.values()
                        if isinstance(value, dict)
                    ):
                        errors.append(f"{prefix}: candidate derivation contains judgment errors")
                    options = {str(key): "" for key in input_judgments}
                    replay = normalize_answer(
                        str(derivation.get("answer_format", "")),
                        input_judgments,
                        options,
                    )
                elif method == "agent.normalize_answer.normalize_tf_verdict":
                    if require_candidate_eligible and str(
                        derivation.get("input_verdict", "")
                    ) not in {"true", "false"}:
                        errors.append(f"{prefix}: candidate TF verdict is uncertain/error")
                    replay = normalize_tf_verdict(
                        str(derivation.get("input_verdict", "")),
                        {"A": "", "B": ""},
                        fallback_answer=str(derivation.get("fallback_answer", "A")),
                    )
                else:
                    raise ValueError(f"unknown normalizer {method!r}")
                if str(replay["answer"]) != str(item.get("answer", "")):
                    errors.append(f"{prefix}: deterministic normalizer replay changed answer")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{prefix}: unable to replay answer derivation: {exc}")

        qid_calls = [
            call
            for call in calls
            if str((call.get("context") or {}).get("qid", "")) == qid
            and str(call.get("call_id", "")) in set(map(str, item.get("trace_call_ids") or []))
        ]
        if require_candidate_eligible:
            all_qid_call_ids = {
                str(call.get("call_id", ""))
                for call in calls
                if str((call.get("context") or {}).get("qid", "")) == qid
            }
            if all_qid_call_ids != set(map(str, item.get("trace_call_ids") or [])):
                errors.append(f"{prefix}: qid has orphaned or cross-linked API calls")
        if (
            sum(int((call.get("usage") or {}).get("prompt_tokens") or 0) for call in qid_calls)
            != int(item.get("prompt_tokens") or 0)
            or sum(
                int((call.get("usage") or {}).get("completion_tokens") or 0)
                for call in qid_calls
            )
            != int(item.get("completion_tokens") or 0)
            or sum(int((call.get("usage") or {}).get("total_tokens") or 0) for call in qid_calls)
            != int(item.get("total_tokens") or 0)
        ):
            errors.append(f"{prefix}: call token totals differ from answer derivation")
        method = str((item.get("answer_derivation") or {}).get("method", ""))
        if method == "agent.normalize_answer.normalize_answer":
            input_judgments = (item.get("answer_derivation") or {}).get(
                "input_judgments", {}
            )
            for option_key, expected in input_judgments.items():
                matches = [
                    call
                    for call in qid_calls
                    if str((call.get("context") or {}).get("option_key", ""))
                    == str(option_key)
                ]
                if len(matches) != 1:
                    errors.append(
                        f"{prefix}: expected exactly one raw call for option {option_key}"
                    )
                    continue
                parsed_raw = extract_json_from_text(str(matches[0].get("response_content", "")))
                if not isinstance(parsed_raw, dict) or str(
                    parsed_raw.get("judgment", "")
                ).strip().lower() != str(
                    (expected or {}).get("judgment", "")
                ).strip().lower():
                    errors.append(
                        f"{prefix}: option {option_key} derivation differs from raw verdict"
                    )
        elif method == "agent.normalize_answer.normalize_tf_verdict":
            if not qid_calls:
                errors.append(f"{prefix}: TF derivation has no raw calls")
            else:
                parsed_raw = extract_json_from_text(
                    str(qid_calls[-1].get("response_content", ""))
                )
                if not isinstance(parsed_raw, dict) or str(
                    parsed_raw.get("verdict", "")
                ).strip().lower() != str(
                    (item.get("answer_derivation") or {}).get("input_verdict", "")
                ).strip().lower():
                    errors.append(f"{prefix}: TF derivation differs from final raw verdict")
        for call_id in item.get("trace_call_ids") or []:
            matching = next(
                (call for call in calls if str(call.get("call_id")) == str(call_id)),
                None,
            )
            if matching is not None and str((matching.get("context") or {}).get("qid", "")) != qid:
                errors.append(f"{prefix}: call {call_id} belongs to a different qid")

    configured_qids = [str(value) for value in (manifest.get("config") or {}).get("qids", [])]
    derivation_qids = [str(item.get("qid", "")) for item in derivations]
    if require_candidate_eligible and configured_qids != derivation_qids:
        errors.append("trace derivation qids/order differ from frozen run config")
    observed_served_models = sorted(
        {
            str(call.get("response_model"))
            for call in calls
            if call.get("response_model")
        }
    )
    if observed_served_models != list(manifest.get("served_models") or []):
        errors.append("served model summary differs from call trace")

    if artifact_dir is not None:
        artifact_dir = artifact_dir.resolve()
        recorded = manifest.get("output_artifacts") or {}
        for path in bundle_paths(artifact_dir):
            if not path.is_file():
                errors.append(f"artifact missing: {path}")
                continue
            entry = recorded.get(path.name) or {}
            if entry.get("sha256") != sha256_file(path):
                errors.append(f"artifact hash differs from trace: {path.name}")
        evidence_path = artifact_dir / "evidence.json"
        try:
            evidence_records = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence_by_qid = {
                str(record.get("qid", "")): record
                for record in evidence_records
                if isinstance(record, dict)
            }
            for derivation in derivations:
                qid = str(derivation.get("qid", ""))
                record = evidence_by_qid.get(qid)
                if record is None:
                    errors.append(f"artifact evidence missing traced qid: {qid}")
                    continue
                if str(record.get("trace_run_id", "")) != trace_run_id:
                    errors.append(f"artifact evidence trace_run_id mismatch: {qid}")
                if str(record.get("answer", "")) != str(derivation.get("answer", "")):
                    errors.append(f"artifact evidence answer differs from derivation: {qid}")
                if record.get("answer_derivation") != derivation.get(
                    "answer_derivation"
                ):
                    errors.append(
                        f"artifact evidence answer_derivation differs from trace: {qid}"
                    )
                if int(record.get("total_tokens") or 0) != int(
                    derivation.get("total_tokens") or 0
                ):
                    errors.append(f"artifact evidence tokens differ from derivation: {qid}")
                if int(record.get("prompt_tokens") or 0) != int(
                    derivation.get("prompt_tokens") or 0
                ) or int(record.get("completion_tokens") or 0) != int(
                    derivation.get("completion_tokens") or 0
                ):
                    errors.append(f"artifact evidence prompt/completion tokens differ: {qid}")
                if sha256_json(record.get("retrieval", {})) != derivation.get(
                    "retrieval_sha256"
                ):
                    errors.append(f"artifact evidence retrieval differs from derivation: {qid}")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"unable to correlate evidence artifact with trace: {exc}")
    if not calls:
        errors.append("trace contains no API calls")
    if not derivations:
        errors.append("trace contains no answer derivations")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "trace_run_id": manifest.get("trace_run_id"),
        "call_count": len(calls),
        "derivation_count": len(derivations),
        "manifest": manifest,
    }


def freeze_candidate(
    candidate_dir: Path,
    *,
    parent_dir: Path,
    experiment_id: str,
    pipeline_version: str,
    parent_version: str,
    trace_dir: Path | None,
    generation_mode: str,
    selection_path: Path | None = None,
    trace_artifact_dir: Path | None = None,
) -> Path:
    """冻结候选三件套和 trace；盲标揭晓时间后续单独登记。"""
    candidate_dir = candidate_dir.resolve()
    parent_dir = parent_dir.resolve()
    submission_report = validate_submission_files(*bundle_paths(candidate_dir))
    if not submission_report["ok"]:
        raise ValueError(
            "candidate submission validation failed before freeze: "
            + "; ".join(submission_report["errors"])
        )
    artifacts = {
        path.name: {"path": display_path(path), "sha256": sha256_file(path)}
        for path in bundle_paths(candidate_dir)
    }
    parent_artifacts = {
        path.name: {"path": display_path(path), "sha256": sha256_file(path)}
        for path in bundle_paths(parent_dir)
    }
    if generation_mode not in {
        "byte_identical_parent_copy",
        "traced_rerun_plus_frozen_parent",
    }:
        raise ValueError(f"unsupported candidate generation_mode: {generation_mode}")
    if trace_dir is None:
        if generation_mode != "byte_identical_parent_copy" or selection_path is not None:
            raise ValueError("untraced freeze is allowed only for byte-identical parent copy")
        if {
            name: entry["sha256"] for name, entry in artifacts.items()
        } != {
            name: entry["sha256"] for name, entry in parent_artifacts.items()
        }:
            raise ValueError("untraced parent-copy candidate is not byte-identical to parent")
    elif generation_mode != "traced_rerun_plus_frozen_parent" or selection_path is None:
        raise ValueError("traced candidate freeze requires the governed generation mode and selection")
    trace: dict[str, Any] | None = None
    if trace_dir is not None:
        trace_dir = trace_dir.resolve()
        if trace_artifact_dir is None:
            raise ValueError("trace_artifact_dir is required when freezing a traced candidate")
        trace_report = validate_trace_directory(
            trace_dir,
            artifact_dir=trace_artifact_dir,
            require_candidate_eligible=True,
            require_current_code_match=True,
        )
        if not trace_report["ok"]:
            raise ValueError(
                "agent trace gate failed before candidate freeze: "
                + "; ".join(trace_report["errors"])
            )
        selection_payload = load_frozen_selection(selection_path.resolve())
        traced_config = trace_report["manifest"].get("config", {})
        if traced_config.get("selection_sha256") != sha256_file(selection_path.resolve()):
            raise ValueError("candidate selection differs from the traced selection")
        if [str(value) for value in traced_config.get("qids", [])] != [
            str(value) for value in selection_payload["qids"]
        ]:
            raise ValueError("candidate selection qids differ from traced qids")
        if str(traced_config.get("experiment_id", "")) != experiment_id:
            raise ValueError("candidate experiment_id differs from traced config")
        if str(traced_config.get("pipeline_version", "")) != pipeline_version:
            raise ValueError("candidate pipeline_version differs from traced config")
        partition_errors = _validate_candidate_parent_partition(
            candidate_dir,
            parent_dir,
            traced_qids=[str(value) for value in traced_config.get("qids", [])],
            selection=selection_payload,
            trace_run_id=str(trace_report.get("trace_run_id", "")),
            parent_version=parent_version,
        )
        if partition_errors:
            raise ValueError(
                "candidate/parent trace partition failed: "
                + "; ".join(partition_errors)
            )
        frozen_trace_dir = candidate_dir / "agent_trace"
        if frozen_trace_dir.exists():
            raise FileExistsError(f"candidate trace already exists: {frozen_trace_dir}")
        shutil.copytree(trace_dir, frozen_trace_dir)
        manifest_path = frozen_trace_dir / "trace_manifest.json"
        trace = {
            "dir": display_path(frozen_trace_dir),
            "manifest": display_path(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
        }
    selection: dict[str, str] | None = None
    if selection_path is not None:
        selection_path = selection_path.resolve()
        selection = {
            "path": display_path(selection_path),
            "sha256": sha256_file(selection_path),
        }
    payload = {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "pipeline_version": pipeline_version,
        "parent_version": parent_version,
        "generation_mode": generation_mode,
        "candidate_dir": display_path(candidate_dir),
        "parent_dir": display_path(parent_dir),
        "candidate_frozen_at": now_iso(),
        "artifacts": artifacts,
        "parent_artifacts": parent_artifacts,
        "agent_trace": trace,
        "blind_selection": selection,
        "prospective_label_gate": "AWAITING_SEPARATE_LABEL_REVEAL_RECORD",
    }
    path = candidate_dir / "candidate_freeze.json"
    if path.exists():
        raise FileExistsError(f"candidate freeze already exists: {path}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_aware_datetime(value: str, *, field: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include an explicit timezone offset")
    return parsed


def _load_completed_label_results(
    labels_path: Path,
    selection: dict[str, Any],
) -> dict[str, Any]:
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("label results must be a JSON object")
    if payload.get("complete") is not True or payload.get("errors") != []:
        raise ValueError("label results must have complete=true and errors=[]")
    results = payload.get("results")
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        raise ValueError("label results must contain a results object list")
    expected_qids = [str(qid) for qid in selection["qids"]]
    result_qids = [str(item.get("qid", "")) for item in results]
    if result_qids != expected_qids:
        raise ValueError("label result qids/order must exactly match the frozen selection")
    if payload.get("selection_id") != selection.get("selection_id"):
        raise ValueError("label results selection_id differs from frozen selection")
    if int(payload.get("expected_count") or 0) != len(expected_qids) or int(
        payload.get("validated_count") or 0
    ) != len(expected_qids):
        raise ValueError("label result counts do not match the frozen selection")
    for item in results:
        if not str(item.get("answer", "")) or not str(item.get("completed_at", "")):
            raise ValueError(f"label result is incomplete: {item.get('qid')}")
        parse_aware_datetime(
            str(item["completed_at"]), field=f"{item.get('qid')}.completed_at"
        )
    return payload


def register_label_reveal(
    candidate_dir: Path,
    *,
    labels_path: Path,
) -> Path:
    """揭标后写独立不可覆盖记录；绝不回写 candidate_freeze.json。"""
    candidate_dir = candidate_dir.resolve()
    pending_report = validate_candidate_freeze(candidate_dir)
    if not pending_report["ok"] or pending_report["temporal_gate"] != "PENDING_LABEL_REVEAL":
        raise ValueError("candidate freeze must validate in PENDING_LABEL_REVEAL state")
    freeze_path = candidate_dir / "candidate_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("schema_version") != FREEZE_SCHEMA_VERSION:
        raise ValueError("candidate freeze schema mismatch")
    frozen_at = parse_aware_datetime(
        str(freeze.get("candidate_frozen_at", "")), field="candidate_frozen_at"
    )
    revealed_at = datetime.now(timezone.utc).astimezone()
    if not frozen_at < revealed_at:
        raise ValueError(
            "prospective gate failed: candidate_frozen_at must be strictly earlier "
            "than label_revealed_at"
        )
    labels_path = labels_path.resolve()
    if not labels_path.is_file():
        raise FileNotFoundError(f"label result file missing: {labels_path}")
    selection_entry = freeze.get("blind_selection") or {}
    selection_path = resolve_recorded_path(str(selection_entry.get("path", "")))
    selection = load_frozen_selection(selection_path)
    label_payload = _load_completed_label_results(labels_path, selection)
    for item in label_payload["results"]:
        completed_at = parse_aware_datetime(
            str(item["completed_at"]), field=f"{item.get('qid')}.completed_at"
        )
        if completed_at > revealed_at:
            raise ValueError("label completed_at cannot be later than label_revealed_at")
    registered_at = datetime.now(timezone.utc).astimezone()
    payload = {
        "schema_version": LABEL_REVEAL_SCHEMA_VERSION,
        "candidate_dir": display_path(candidate_dir),
        "candidate_freeze": {
            "path": display_path(freeze_path),
            "sha256": sha256_file(freeze_path),
        },
        "labels": {
            "path": display_path(labels_path),
            "sha256": sha256_file(labels_path),
        },
        "candidate_frozen_at": str(freeze["candidate_frozen_at"]),
        "label_revealed_at": revealed_at.isoformat(timespec="microseconds"),
        "registered_at": registered_at.isoformat(timespec="microseconds"),
        "prospective_qids": selection["prospective_qids"],
        "known_before_freeze_qids": selection["known_before_freeze_qids"],
        "prospective_count": len(selection["prospective_qids"]),
        "temporal_gate": "PASS",
    }
    output = candidate_dir / "label_reveal.json"
    if output.exists():
        raise FileExistsError(f"label reveal record already exists: {output}")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def validate_candidate_freeze(
    candidate_dir: Path,
    *,
    label_reveal_path: Path | None = None,
) -> dict[str, Any]:
    candidate_dir = candidate_dir.resolve()
    errors: list[str] = []
    validated_trace_report: dict[str, Any] | None = None
    freeze_path = candidate_dir / "candidate_freeze.json"
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"unable to load candidate freeze: {exc}"]}
    if freeze.get("schema_version") != FREEZE_SCHEMA_VERSION:
        errors.append("candidate freeze schema mismatch")
    submission_report = validate_submission_files(*bundle_paths(candidate_dir))
    if not submission_report["ok"]:
        errors.extend(
            f"candidate submission: {item}" for item in submission_report["errors"]
        )
    if resolve_recorded_path(str(freeze.get("candidate_dir", ""))) != candidate_dir:
        errors.append("candidate freeze candidate_dir does not match the validated directory")
    for field in ("experiment_id", "pipeline_version", "parent_version"):
        if not str(freeze.get(field, "")).strip():
            errors.append(f"candidate freeze {field} is missing")
    generation_mode = str(freeze.get("generation_mode", ""))
    if generation_mode not in {
        "byte_identical_parent_copy",
        "traced_rerun_plus_frozen_parent",
    }:
        errors.append("candidate freeze generation_mode is invalid")
    try:
        frozen_at = parse_aware_datetime(
            str(freeze.get("candidate_frozen_at", "")), field="candidate_frozen_at"
        )
    except ValueError as exc:
        errors.append(str(exc))
        frozen_at = None
    expected_candidate_paths = {
        path.name: path.resolve() for path in bundle_paths(candidate_dir)
    }
    candidate_entries = freeze.get("artifacts") or {}
    if not isinstance(candidate_entries, dict) or set(candidate_entries) != set(
        expected_candidate_paths
    ):
        errors.append("candidate freeze must contain exactly the three submission artifacts")
        candidate_entries = candidate_entries if isinstance(candidate_entries, dict) else {}
    for name, entry in candidate_entries.items():
        path = resolve_recorded_path(str((entry or {}).get("path", "")))
        if name in expected_candidate_paths and path != expected_candidate_paths[name]:
            errors.append(f"frozen candidate artifact path is not canonical: {name}")
        if not path.is_file() or sha256_file(path) != (entry or {}).get("sha256"):
            errors.append(f"frozen candidate artifact changed or is missing: {name}")
    parent_dir = resolve_recorded_path(str(freeze.get("parent_dir", "")))
    expected_parent_paths = {
        path.name: path.resolve() for path in bundle_paths(parent_dir)
    }
    parent_entries = freeze.get("parent_artifacts") or {}
    if not isinstance(parent_entries, dict) or set(parent_entries) != set(
        expected_parent_paths
    ):
        errors.append("candidate freeze must contain exactly the three parent artifacts")
        parent_entries = parent_entries if isinstance(parent_entries, dict) else {}
    parent_hashes: dict[str, str] = {}
    for name, entry in parent_entries.items():
        path = resolve_recorded_path(str((entry or {}).get("path", "")))
        expected = str((entry or {}).get("sha256", ""))
        parent_hashes[name] = expected
        if name in expected_parent_paths and path != expected_parent_paths[name]:
            errors.append(f"frozen parent artifact path is not canonical: {name}")
        if not path.is_file() or sha256_file(path) != expected:
            errors.append(f"frozen parent artifact changed or is missing: {name}")
    if generation_mode == "byte_identical_parent_copy":
        candidate_hashes = {
            name: str((entry or {}).get("sha256", ""))
            for name, entry in candidate_entries.items()
        }
        if candidate_hashes != parent_hashes or freeze.get("agent_trace") is not None:
            errors.append("parent-copy freeze is not byte-identical/untraced")
        if freeze.get("blind_selection") is not None:
            errors.append("parent-copy freeze cannot claim a blind selection")
    if generation_mode == "traced_rerun_plus_frozen_parent" and not freeze.get("agent_trace"):
        errors.append("traced candidate freeze is missing agent_trace")
    trace = freeze.get("agent_trace")
    if trace:
        expected_trace_dir = (candidate_dir / "agent_trace").resolve()
        if resolve_recorded_path(str(trace.get("dir", ""))) != expected_trace_dir:
            errors.append("frozen agent trace directory is not canonical")
        manifest_path = resolve_recorded_path(str(trace.get("manifest", "")))
        if manifest_path != expected_trace_dir / "trace_manifest.json":
            errors.append("frozen agent trace manifest path is not canonical")
        if not manifest_path.is_file() or sha256_file(manifest_path) != trace.get(
            "manifest_sha256"
        ):
            errors.append("frozen agent trace manifest changed or is missing")
        else:
            trace_report = validate_trace_directory(
                manifest_path.parent,
                require_candidate_eligible=True,
                require_current_code_match=False,
                allow_frozen_relocation=True,
            )
            if not trace_report["ok"]:
                errors.extend(f"frozen trace: {item}" for item in trace_report["errors"])
            else:
                validated_trace_report = trace_report
                try:
                    trace_finished_at = parse_aware_datetime(
                        str(trace_report["manifest"].get("finished_at", "")),
                        field="trace.finished_at",
                    )
                    if frozen_at is None or trace_finished_at > frozen_at:
                        errors.append(
                            "trace.finished_at must not be later than candidate_frozen_at"
                        )
                    candidate_manifest = json.loads(
                        (candidate_dir / "run_manifest.json").read_text(encoding="utf-8")
                    )
                    candidate_finished_value = candidate_manifest.get("run_finished_at")
                    if candidate_finished_value:
                        candidate_finished_at = parse_aware_datetime(
                            str(candidate_finished_value),
                            field="candidate.run_finished_at",
                        )
                        if frozen_at is None or candidate_finished_at > frozen_at:
                            errors.append(
                                "candidate.run_finished_at must not be later than "
                                "candidate_frozen_at"
                            )
                    else:
                        errors.append("candidate run_finished_at is missing")
                    candidate_evidence = json.loads(
                        (candidate_dir / "evidence.json").read_text(encoding="utf-8")
                    )
                    gate = candidate_manifest.get("agent_trace_gate") or {}
                    trace_run_id = str(trace_report.get("trace_run_id", ""))
                    if gate.get("status") != "PASS":
                        errors.append("candidate manifest trace gate is not PASS")
                    if str(gate.get("trace_run_id", "")) != trace_run_id:
                        errors.append("candidate manifest references a different trace run")
                    traced_qids = [str(value) for value in gate.get("fresh_traced_qids", [])]
                    configured_qids = [
                        str(value)
                        for value in trace_report["manifest"].get("config", {}).get("qids", [])
                    ]
                    if traced_qids != configured_qids:
                        errors.append("candidate fresh qids differ from frozen trace qids")
                    if str(candidate_manifest.get("experiment_id", "")) != str(
                        freeze.get("experiment_id", "")
                    ):
                        errors.append("candidate experiment_id differs from freeze")
                    if str(candidate_manifest.get("pipeline_version", "")) != str(
                        freeze.get("pipeline_version", "")
                    ):
                        errors.append("candidate pipeline_version differs from freeze")
                    derivations = _read_jsonl(manifest_path.parent / "derivations.jsonl")
                    derivation_by_qid = {
                        str(item.get("qid", "")): item for item in derivations
                    }
                    evidence_by_qid = {
                        str(item.get("qid", "")): item
                        for item in candidate_evidence
                        if isinstance(item, dict)
                    }
                    for qid in traced_qids:
                        derivation = derivation_by_qid.get(qid)
                        record = evidence_by_qid.get(qid)
                        if derivation is None or record is None:
                            errors.append(f"candidate/trace correlation missing qid: {qid}")
                            continue
                        if str(record.get("trace_run_id", "")) != trace_run_id:
                            errors.append(f"candidate traced qid has wrong trace_run_id: {qid}")
                        if str(record.get("answer", "")) != str(derivation.get("answer", "")):
                            errors.append(f"candidate answer differs from trace derivation: {qid}")
                        if int(record.get("total_tokens") or 0) != int(
                            derivation.get("total_tokens") or 0
                        ):
                            errors.append(f"candidate tokens differ from trace derivation: {qid}")
                        if int(record.get("prompt_tokens") or 0) != int(
                            derivation.get("prompt_tokens") or 0
                        ) or int(record.get("completion_tokens") or 0) != int(
                            derivation.get("completion_tokens") or 0
                        ):
                            errors.append(
                                f"candidate prompt/completion tokens differ from trace: {qid}"
                            )
                        if sha256_json(record.get("retrieval", {})) != derivation.get(
                            "retrieval_sha256"
                        ):
                            errors.append(f"candidate retrieval differs from trace: {qid}")
                except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"unable to correlate frozen candidate and trace: {exc}")
    selection = freeze.get("blind_selection")
    if selection:
        selection_path = resolve_recorded_path(str(selection.get("path", "")))
        if not selection_path.is_file() or sha256_file(selection_path) != selection.get(
            "sha256"
        ):
            errors.append("blind selection changed or is missing")
        else:
            try:
                selection_payload = load_frozen_selection(selection_path)
                if trace:
                    candidate_manifest = json.loads(
                        (candidate_dir / "run_manifest.json").read_text(encoding="utf-8")
                    )
                    gate = candidate_manifest.get("agent_trace_gate") or {}
                    if [str(value) for value in gate.get("prospective_qids", [])] != [
                        str(value) for value in selection_payload["prospective_qids"]
                    ]:
                        errors.append(
                            "candidate prospective_qids differ from frozen selection"
                        )
                    if [
                        str(value)
                        for value in gate.get("known_before_freeze_qids", [])
                    ] != [
                        str(value)
                        for value in selection_payload["known_before_freeze_qids"]
                    ]:
                        errors.append(
                            "candidate known-before-freeze qids differ from selection"
                        )
                    if validated_trace_report is not None:
                        traced_config = validated_trace_report["manifest"].get(
                            "config", {}
                        )
                        errors.extend(
                            _validate_candidate_parent_partition(
                                candidate_dir,
                                parent_dir,
                                traced_qids=[
                                    str(value)
                                    for value in traced_config.get("qids", [])
                                ],
                                selection=selection_payload,
                                trace_run_id=str(
                                    validated_trace_report.get("trace_run_id", "")
                                ),
                                parent_version=str(freeze.get("parent_version", "")),
                            )
                        )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid frozen blind selection: {exc}")
    elif generation_mode == "traced_rerun_plus_frozen_parent":
        errors.append("traced candidate freeze is missing blind_selection")

    temporal_status = "PENDING_LABEL_REVEAL"
    reveal_path = label_reveal_path or (candidate_dir / "label_reveal.json")
    if reveal_path.exists():
        try:
            reveal = json.loads(reveal_path.read_text(encoding="utf-8"))
            if reveal.get("schema_version") != LABEL_REVEAL_SCHEMA_VERSION:
                errors.append("label reveal schema mismatch")
            if resolve_recorded_path(str(reveal.get("candidate_dir", ""))) != candidate_dir:
                errors.append("label reveal candidate_dir mismatch")
            if str(reveal.get("candidate_frozen_at", "")) != str(
                freeze.get("candidate_frozen_at", "")
            ):
                errors.append("label reveal candidate_frozen_at mismatch")
            if reveal.get("temporal_gate") != "PASS":
                errors.append("label reveal temporal_gate is not PASS")
            freeze_ref = reveal.get("candidate_freeze") or {}
            if resolve_recorded_path(str(freeze_ref.get("path", ""))) != freeze_path:
                errors.append("label reveal candidate freeze path mismatch")
            if freeze_ref.get("sha256") != sha256_file(freeze_path):
                errors.append("label reveal references a different candidate freeze")
            labels = reveal.get("labels") or {}
            labels_path = resolve_recorded_path(str(labels.get("path", "")))
            if not labels_path.is_file() or sha256_file(labels_path) != labels.get("sha256"):
                errors.append("revealed label artifact changed or is missing")
            selection_entry = freeze.get("blind_selection") or {}
            selection_path = resolve_recorded_path(str(selection_entry.get("path", "")))
            selection_payload = load_frozen_selection(selection_path)
            label_payload = _load_completed_label_results(labels_path, selection_payload)
            revealed_at = parse_aware_datetime(
                str(reveal.get("label_revealed_at", "")), field="label_revealed_at"
            )
            registered_at = parse_aware_datetime(
                str(reveal.get("registered_at", "")), field="registered_at"
            )
            if revealed_at > registered_at:
                errors.append("label_revealed_at cannot be later than registered_at")
            if [str(value) for value in reveal.get("prospective_qids", [])] != [
                str(value) for value in selection_payload["prospective_qids"]
            ]:
                errors.append("label reveal prospective_qids differ from frozen selection")
            if [str(value) for value in reveal.get("known_before_freeze_qids", [])] != [
                str(value) for value in selection_payload["known_before_freeze_qids"]
            ]:
                errors.append(
                    "label reveal known_before_freeze_qids differ from frozen selection"
                )
            if int(reveal.get("prospective_count") or -1) != len(
                selection_payload["prospective_qids"]
            ):
                errors.append("label reveal prospective_count mismatch")
            for item in label_payload["results"]:
                completed_at = parse_aware_datetime(
                    str(item["completed_at"]),
                    field=f"{item.get('qid')}.completed_at",
                )
                if completed_at > revealed_at:
                    errors.append(
                        "label completed_at is later than label_revealed_at: "
                        f"{item.get('qid')}"
                    )
            if frozen_at is None or not frozen_at < revealed_at:
                errors.append(
                    "prospective gate failed: candidate_frozen_at is not strictly earlier "
                    "than label_revealed_at"
                )
            else:
                temporal_status = "PASS"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid label reveal record: {exc}")
    return {
        "ok": not errors,
        "errors": errors,
        "candidate_frozen_at": freeze.get("candidate_frozen_at"),
        "temporal_gate": temporal_status,
    }
