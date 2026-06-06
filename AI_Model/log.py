import io
import sys
from multiprocessing import Queue, Manager
from typing import Optional
from datetime import datetime
from pathlib import Path

# Debug mode flag
from .config import SharedState

# Global log queue (optional)
LOG_QUEUE: Optional[Queue] = None
DEBUG = True
_LOG_FILE: Optional[Path] = None

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def init_log_queue(queue: Optional[Queue], state):
    """
    Call ONCE from main process to enable centralized logging.
    Also determines whether to log to console (debug) or file (production).
    """
    global LOG_QUEUE, DEBUG, _LOG_FILE
    LOG_QUEUE = queue
    if state:
        DEBUG = state.get_debug_mode()
    else:
        DEBUG = True

    if not DEBUG:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        _LOG_FILE = Path("log") / f"iniya.{timestamp}.debugf.log"
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Write a header so the file exists immediately
        _LOG_FILE.write_text(
            f"Iniya log — started {datetime.now().isoformat()}\n",
            encoding="utf-8"
        )


def log(msg: str, task: str = "GENERAL"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{task}] {msg}"

    if DEBUG:
        # Queue → drain loop → console
        if LOG_QUEUE is not None:
            try:
                LOG_QUEUE.put(formatted)
                return
            except Exception:
                pass
        print(formatted, flush=True)
    else:
        # Queue → drain loop → file
        if LOG_QUEUE is not None:
            try:
                LOG_QUEUE.put(formatted)
                return
            except Exception:
                pass
        # Fallback: write directly to file
        _write_to_file(formatted)


def _write_to_file(line: str):
    if _LOG_FILE is None:
        return
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # nothing we can do if the file is unwritable


def log_drain_loop(queue, stop_event):
    while not stop_event.is_set() or not queue.empty():
        try:
            msg = queue.get(timeout=0.1)
            if DEBUG:
                print(msg, flush=True)
            else:
                _write_to_file(msg)
        except Exception:
            pass