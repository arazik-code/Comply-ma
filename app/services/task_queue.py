"""
File d'attente de tâches en-processus.

Remplace Celery/RQ pour les déploiements mono-processus.
Gère les tâches asynchrones avec retry, priorité, et timeout.
"""
import asyncio
import logging
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("app.task_queue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


class TaskPriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class TaskDefinition:
    name: str
    func: Callable[..., Coroutine]
    priority: TaskPriority = TaskPriority.NORMAL
    max_retries: int = 3
    retry_delay: float = 5.0  # seconds
    timeout: float = 300.0  # 5 minutes


@dataclass
class TaskResult:
    task_id: str
    name: str
    status: TaskStatus
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None


class InProcessTaskQueue:
    """
    File d'attente de tâches en-processus avec :
    - Priorité (CRITICAL > HIGH > NORMAL > LOW)
    - Retry automatique avec délai configurable
    - Timeout par tâche
    - Historique des résultats
    """

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._tasks: dict[str, TaskDefinition] = {}
        self._queue: deque = deque()
        self._results: dict[str, TaskResult] = {}
        self._running: int = 0
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._processing = False

    def register(self, task_def: TaskDefinition):
        """Enregistre un type de tâche."""
        self._tasks[task_def.name] = task_def

    async def submit(
        self,
        task_name: str,
        *args,
        priority: TaskPriority = TaskPriority.NORMAL,
        **kwargs,
    ) -> str:
        """
        Soumet une tâche à la file d'attente.

        Returns:
            ID de la tâche soumise
        """
        if task_name not in self._tasks:
            raise ValueError(f"Tâche inconnue: {task_name}")

        task_id = uuid.uuid4().hex[:16]
        result = TaskResult(
            task_id=task_id,
            name=task_name,
            status=TaskStatus.PENDING,
        )
        self._results[task_id] = result

        self._queue.append((task_id, task_name, args, kwargs, priority))
        # Trier par priorité décroissante
        self._queue = deque(sorted(self._queue, key=lambda x: x[4].value, reverse=True))

        logger.info("task_submitted", extra={"task_id": task_id, "name": task_name, "priority": priority.value})
        return task_id

    async def process_next(self) -> bool:
        """Traite la prochaine tâche en attente. Retourne True si une tâche a été traitée."""
        if not self._queue:
            return False

        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)

        # Vérifie la capacité sans bloquer : si toutes les tâches sont en cours,
        # on laisse la tâche dans la file pour un traitement ultérieur.
        if self._running >= self.max_concurrent:
            return False

        await self._semaphore.acquire()
        try:
            task_id, task_name, args, kwargs, priority = self._queue.popleft()
        except IndexError:
            self._semaphore.release()
            return False
        result = self._results[task_id]
        task_def = self._tasks[task_name]

        result.status = TaskStatus.RUNNING
        result.started_at = time.time()
        self._running += 1

        try:
            timeout = task_def.timeout
            coro = task_def.func(*args, **kwargs)
            task_result = await asyncio.wait_for(coro, timeout=timeout)
            result.result = task_result
            result.status = TaskStatus.SUCCESS
            result.attempts += 1
            logger.info("task_success", extra={"task_id": task_id, "name": task_name})

        except asyncio.TimeoutError:
            result.error = f"Timeout après {task_def.timeout}s"
            result.status = TaskStatus.FAILED
            result.attempts += 1
            logger.warning("task_timeout", extra={"task_id": task_id, "name": task_name, "timeout": task_def.timeout})

        except Exception as e:
            result.attempts += 1
            if result.attempts <= task_def.max_retries:
                result.status = TaskStatus.RETRY
                retry_delay = task_def.retry_delay * (2 ** (result.attempts - 1))
                self._queue.append((task_id, task_name, args, kwargs, priority))
                logger.warning("task_retry", extra={
                    "task_id": task_id,
                    "name": task_name,
                    "attempt": result.attempts,
                    "retry_delay": retry_delay,
                    "error": str(e),
                })
                # Schedule retry
                asyncio.get_event_loop().call_later(
                    retry_delay,
                    lambda: asyncio.ensure_future(self.process_next()),
                )
            else:
                result.error = str(e)
                result.status = TaskStatus.FAILED
                logger.error("task_failed", extra={
                    "task_id": task_id,
                    "name": task_name,
                    "attempts": result.attempts,
                    "error": str(e),
                })
        finally:
            result.completed_at = time.time()
            self._running -= 1
            self._semaphore.release()

        return True

    async def process_all(self):
        """Traite toutes les tâches en attente."""
        while self._queue or self._running > 0:
            if self._queue:
                await self.process_next()
            else:
                await asyncio.sleep(0.1)

    def get_result(self, task_id: str) -> Optional[TaskResult]:
        return self._results.get(task_id)

    def get_stats(self) -> dict:
        return {
            "pending": len(self._queue),
            "running": self._running,
            "total_results": len(self._results),
            "by_status": {
                status.value: sum(1 for r in self._results.values() if r.status == status)
                for status in TaskStatus
            },
        }


# --- Instance globale ---
_queue: Optional[InProcessTaskQueue] = None


def get_task_queue() -> InProcessTaskQueue:
    """Retourne l'instance globale de la file d'attente."""
    global _queue
    if _queue is None:
        _queue = InProcessTaskQueue()
        _register_default_tasks()
    return _queue


def _register_default_tasks():
    """Enregistre les tâches par défaut."""
    queue = get_task_queue()

    async def _submit_to_dgi(xml_bytes: bytes, invoice_id: str, company_id: str):
        from app.services.clearance_queue import process_queue
        process_queue()
        return {"status": "submitted", "invoice_id": invoice_id}

    async def _send_email(to: str, subject: str, body: str, attachments: list = None):
        from app.services.email import send_email
        return await send_email(to, subject, body, attachments or [])

    async def _verify_invoice(xml_bytes: bytes, invoice_id: str):
        from app.services.dgi.verification import verify_supplier_invoice
        return await verify_supplier_invoice(xml_bytes, invoice_id)

    queue.register(TaskDefinition(name="dgi_submit", func=_submit_to_dgi, max_retries=5, retry_delay=10))
    queue.register(TaskDefinition(name="send_email", func=_send_email, max_retries=3, retry_delay=5))
    queue.register(TaskDefinition(name="verify_invoice", func=_verify_invoice, max_retries=2, retry_delay=30))
