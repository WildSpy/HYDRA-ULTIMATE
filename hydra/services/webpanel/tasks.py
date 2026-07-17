"""hydra/services/webpanel/tasks.py — фоновые задачи веб-панели.

Долгие операции (установка sing-box, apply_config, установка плагинов, certbot,
диагностика) выполняются в отдельных потоках. stdout/stderr перехватывается
построчно в буфер прогресса, чтобы UI мог показывать «живой» вывод через
поллинг GET /api/tasks/<id>.
"""
from __future__ import annotations

import io
import threading
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_MAX_KEEP = 100          # сколько завершённых задач держать в памяти
_PRUNE_AFTER = 3600      # секунд: удалять завершённые задачи старше часа


@dataclass
class Task:
    id: str
    kind: str
    status: str = "running"          # running | success | error
    progress: list[str] = field(default_factory=list)
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "result": self.result if _jsonable(self.result) else str(self.result),
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


def _jsonable(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str, list, dict))


class _LineSink(io.TextIOBase):
    """Файлоподобный объект: копит текст и режет на строки в task.progress."""

    def __init__(self, task: Task, lock: threading.Lock):
        self._task = task
        self._lock = lock
        self._buf = ""

    def write(self, s: str) -> int:  # type: ignore[override]
        if not s:
            return 0
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = line.rstrip("\r")
                if line:
                    self._task.progress.append(line)
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        with self._lock:
            if self._buf.strip():
                self._task.progress.append(self._buf.rstrip("\r\n"))
                self._buf = ""


class TaskManager:
    """Реестр фоновых задач (in-memory, на время жизни процесса)."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, thunk: Callable[[], Any]) -> str:
        """Запускает thunk() в фоне; возвращает task_id."""
        self._prune()
        task = Task(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._tasks[task.id] = task
        sink_lock = threading.Lock()
        sink = _LineSink(task, sink_lock)

        def _runner():
            try:
                with redirect_stdout(sink), redirect_stderr(sink):
                    result = thunk()
                sink.flush()
                with self._lock:
                    task.result = result
                    task.status = "success"
                    task.finished_at = time.time()
            except Exception as exc:  # noqa: BLE001 — сохраняем любую ошибку в задачу
                sink.flush()
                with self._lock:
                    task.error = f"{type(exc).__name__}: {exc}"
                    task.progress.append(task.error)
                    task.progress.extend(traceback.format_exc().splitlines()[-5:])
                    task.status = "error"
                    task.finished_at = time.time()

        threading.Thread(target=_runner, name=f"task-{kind}", daemon=True).start()
        return task.id

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in sorted(
                self._tasks.values(), key=lambda t: t.created_at, reverse=True)]

    def _prune(self) -> None:
        now = time.time()
        with self._lock:
            done = [t for t in self._tasks.values() if t.finished_at]
            for t in done:
                if now - (t.finished_at or now) > _PRUNE_AFTER:
                    self._tasks.pop(t.id, None)
            # жёсткий лимит на всякий случай
            if len(self._tasks) > _MAX_KEEP:
                oldest = sorted(self._tasks.values(), key=lambda t: t.created_at)
                for t in oldest[: len(self._tasks) - _MAX_KEEP]:
                    if t.finished_at:
                        self._tasks.pop(t.id, None)


# Глобальный менеджер задач панели.
MANAGER = TaskManager()
