"""
py_cui.py — Terminal UI for Iniya
Mirrors the same pipe protocol as py_web.py so it can be dropped into main.py.
"""

import json
import sys
import threading
import time
from datetime import datetime
from threading import Thread

import re as _re

from AI_Model.log import log
from AI_Model.config import SharedState
from AI_Model.audio import AudioClient
from AI_Model.memory.memory_chat import MainChatHistory
from AI_Model.utils.util import strip_for_tts , _math


def _render_for_display(text: str) -> str:
    """
    Prepare agent reply for terminal display:
      - All LaTeX math delimiters → unicode text via pylatexenc
      - Markdown bold / italic → plain text
      - Markdown headers → plain text (keep the words, drop the #)
    """
    # LaTeX: \[...\]  display math
    text = _re.sub(r'\\\[(.*?)\\\]', _math, text, flags=_re.DOTALL)
    # LaTeX: \(...\)  inline math
    text = _re.sub(r'\\\((.*?)\\\)', _math, text, flags=_re.DOTALL)
    # LaTeX: $$...$$  display math
    text = _re.sub(r'\$\$(.*?)\$\$', _math, text, flags=_re.DOTALL)
    # LaTeX: $...$    inline math
    text = _re.sub(r'\$([^$\n]+?)\$', _math, text)

    # Markdown bold/italic (*** before ** before *)
    text = _re.sub(r'\*{3}(.+?)\*{3}', r'\1', text)
    text = _re.sub(r'\*{2}(.+?)\*{2}', r'\1', text)
    text = _re.sub(r'_{2}(.+?)_{2}',   r'\1', text)
    text = _re.sub(r'\*(.+?)\*',       r'\1', text)

    # Markdown headers  → keep text, drop leading #
    text = _re.sub(r'^#{1,6}\s+', '', text, flags=_re.MULTILINE)

    return text


# ── ANSI colours (Windows Terminal / any modern terminal supports these) ──
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    CYAN    = "\033[36m"
    RED     = "\033[31m"
    MAGENTA = "\033[35m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def _print_header():
    print(f"\n{C.CYAN}{C.BOLD}  ██╗███╗   ██╗██╗██╗   ██╗ █████╗ {C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  ██║████╗  ██║██║╚██╗ ██╔╝██╔══██╗{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  ██║██╔██╗ ██║██║ ╚████╔╝ ███████║{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  ██║██║╚██╗██║██║  ╚██╔╝  ██╔══██║{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  ██║██║ ╚████║██║   ██║   ██║  ██║{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  ╚═╝╚═╝  ╚═══╝╚═╝   ╚═╝   ╚═╝  ╚═╝{C.RESET}")
    print(f"\n{C.GRAY}  CUI Mode  ·  type 'exit' or 'quit' to close{C.RESET}\n")
    print(f"  {C.DIM}{'─' * 50}{C.RESET}\n")


# ── Spinner that runs while the agent is thinking ──
class Spinner:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self, msg="Thinking"):
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, args=(msg,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
        # clear the spinner line
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _spin(self, msg):
        i = 0
        while not self._stop.is_set():
            frame = SPINNER_FRAMES[i % len(SPINNER_FRAMES)]
            sys.stdout.write(f"\r  {C.CYAN}{frame}{C.RESET} {C.DIM}{msg}...{C.RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1


# ── Step tracker for tool calls ──
class StepTracker:
    def __init__(self):
        self._steps = {}   # label → {"line": int, "status": "running"|"ok"|"fail"}
        self._lock = threading.Lock()
        self._start_line = 0

    def reset(self):
        with self._lock:
            self._steps = {}

    def add(self, label: str, detail: str = ""):
        with self._lock:
            short = f"  {C.CYAN}◆{C.RESET} {C.WHITE}{label:<20}{C.RESET}"
            if detail:
                short += f" {C.DIM}{detail[:40]}{C.RESET}"
            print(short)
            self._steps[label] = {"status": "running"}

    def complete(self, label: str):
        with self._lock:
            if label in self._steps:
                self._steps[label]["status"] = "ok"
                self._reprint(label)

    def fail(self, label: str, reason: str = ""):
        with self._lock:
            if label in self._steps:
                self._steps[label]["status"] = "fail"
                self._reprint(label, reason)

    def _reprint(self, label: str, reason: str = ""):
        status = self._steps[label]["status"]
        icon  = f"{C.GREEN}✓{C.RESET}" if status == "ok" else f"{C.RED}✗{C.RESET}"
        line  = f"  {C.CYAN}◆{C.RESET} {C.WHITE}{label:<20}{C.RESET} {icon}"
        if reason:
            line += f"  {C.RED}{C.DIM}{reason[:50]}{C.RESET}"
        # move up N lines from current position is hard without curses,
        # so just reprint inline on a new line with a marker
        print(f"\r\033[K{line}")


# ── Main CUI class ──
class CUI:
    def __init__(self, info_conn, msg_conn, state: SharedState, chatID: str = None, new_chat_id: str = None):
        self.info_conn = info_conn
        self.msg_conn  = msg_conn
        self.state     = state
        self.chatID     = chatID
        self.new_chat_id = new_chat_id

        self._reply_ready   = threading.Event()
        self._chat_ready    = threading.Event()
        self._shutdown      = threading.Event()
        self._spinner       = Spinner()
        self._steps         = StepTracker()
        self._chat_history   = MainChatHistory()  # for potential future use (e.g. /history command)
        self._current_reply = ""
        if state.get_audio_mode():
            self._audio_client = AudioClient()
            self._audio_client.set_input_device(state.get_audio_device_index() if state.get_audio_device_index() is not None else 0)

    def start(self):
        Thread(target=self._listen_info, daemon=True).start()
        Thread(target=self._listen_msg,  daemon=True).start()

        # Request a new chat session
        if self.chatID == 'new':
            if self.new_chat_id:
                self.info_conn.send({"event": "chatChange", "type": "text", "chatID": "new", "newChatID": self.new_chat_id})
            else: 
                self.info_conn.send({"event": "chatChange", "type": "text"})
        elif self.chatID is not None:
            self.info_conn.send({"event": "chatChange", "type": "text", "chatID": self.chatID})
        else:
            self.info_conn.send({"event": "chatChange", "type": "text", "chatID": "master"})

        # Wait for chat to be confirmed before showing prompt
        if not self._chat_ready.wait(timeout=10):
            print(f"{C.RED}  ✗ Chat session failed to start.{C.RESET}")
            return

        self._input_loop()

    # ── Info listener (chatChange / system events from chat_loop) ──
    def _listen_info(self):
        try:
            while not self._shutdown.is_set():
                msg = self.info_conn.recv()
                log(f"INFO MSG RECEIVED: {msg}", "PYWEBVIEW DEBUG")
                event = msg.get("event")

                if event == "chatChange":
                    if msg.get("status") == "success":
                        log(f"Chat changed to {msg['chatID']}", "PYWEBVIEW")
                        self._chat_ready.set()
                    else:
                        print(f"\n{C.RED}  ✗ Chat change failed: {msg.get('error')}{C.RESET}")

                elif event == "system":
                    log(f"System event: {msg.get('data')}", "PYWEBVIEW")

        except Exception as e:
            log(f"receiveInfo crashed: {e}", "PYWEBVIEW ERROR")

    # ── Message listener (tool events + final reply from agent) ──
    def _listen_msg(self):
        try:
            while not self._shutdown.is_set():
                msg = self.msg_conn.recv()
                log(f"RAW MSG RECEIVED: {msg}", "PYWEBVIEW DEBUG")

                event = msg.get("event")
                if event != "message":
                    continue

                data     = msg.get("data", {})
                msg_type = data.get("type")
                content  = data.get("content", {})

                log(f"event=message | type={msg_type}", "PYWEBVIEW DEBUG")

                if msg_type == "toolUse":
                    self._spinner.stop()
                    label  = content.get("name", "")
                    detail = content.get("agent_reply", "")
                    self._steps.add(label, detail)

                elif msg_type == "toolDone":
                    label  = content.get("name", "")
                    failed = content.get("failed", False)
                    if failed:
                        self._steps.fail(label)
                    else:
                        self._steps.complete(label)

                elif msg_type == "toolFailed":
                    label  = content.get("name", "")
                    reason = content.get("reason", "")
                    self._steps.fail(label, reason)
                    log(f"toolFailed: {label} — {reason}", "PYWEBVIEW DEBUG")

                elif msg_type == "finalReply":
                    self._spinner.stop()
                    text = (
                        content.get("clean_text", {}).get("raw")
                        or content.get("text", "")
                    )
                    log(f"finalReply content: {repr(text)}", "PYWEBVIEW DEBUG")
                    self._current_reply = _render_for_display(text)
                    self._reply_ready.set()

                elif msg_type in ("memoryUpdate", "taskUpdate"):
                    log(f"{msg_type}: {content}", "PYWEBVIEW DEBUG")

        except Exception as e:
            log(f"receiveReply crashed: {e}", "PYWEBVIEW ERROR")

    # ── Input loop ──
    def _input_loop(self):
        _print_header()

        while not self._shutdown.is_set():
            try:
                if not self.state.get_audio_mode():
                    user_input = input(f"{C.BOLD}{C.MAGENTA}  You{C.RESET}  {C.DIM}{_ts()}{C.RESET}\n  {C.BOLD}>{C.RESET} ").strip()
                else:
                    import keyboard, time

                    PTT_KEY = "space"

                    print(
                        f"{C.BOLD}{C.MAGENTA}  You (audio mode){C.RESET}  {C.DIM}{_ts()}{C.RESET}\n"
                        f"  {C.BOLD}{C.GRAY}Hold [{PTT_KEY.upper()}] to talk  •  q + Enter to quit{C.RESET}"
                    )

                    quit_event  = threading.Event()
                    press_event = threading.Event()
                    release_event = threading.Event()

                    # Watch for typed quit — runs in background
                    def _watch_quit():
                        try:
                            line = input()
                            if line.strip().lower() in ("q", "quit", "exit"):
                                quit_event.set()
                        except (EOFError, KeyboardInterrupt):
                            quit_event.set()

                    t = threading.Thread(target=_watch_quit, daemon=True)
                    t.start()

                    # Edge-detect press — suppress=True stops Space reaching stdin/key-repeat
                    def _on_press(e):
                        if not press_event.is_set():   # ignore key-repeat firings
                            press_event.set()

                    def _on_release(e):
                        release_event.set()

                    h_press   = keyboard.on_press_key(PTT_KEY,   _on_press,   suppress=True)
                    h_release = keyboard.on_release_key(PTT_KEY, _on_release, suppress=True)

                    # Wait for Space press OR typed quit
                    while not press_event.is_set() and not quit_event.is_set():
                        time.sleep(0.02)

                    try:
                        keyboard.unhook(h_press)
                    except KeyError:
                        pass
                    try:
                        keyboard.unhook(h_release)
                    except KeyError:
                        pass

                    if quit_event.is_set():
                        self._quit()
                        break

                    # ── Recording ──────────────────────────────────────────────────────────
                    self._spinner.start(
                        f"{C.YELLOW}● Recording  {C.DIM}(release [{PTT_KEY.upper()}] to stop){C.RESET}"
                    )
                    self._audio_client.start_recording()

                    release_event.wait()   # blocks cleanly until physical key release — no polling

                    pcm = self._audio_client.stop_recording()
                    self._spinner.stop()

                    self._spinner.start(f"{C.YELLOW}Transcribing...{C.RESET}")
                    user_input = self._audio_client.transcribe(
                        pcm, sample_rate=self._audio_client.SAMPLE_RATE
                    )
                    self._spinner.stop()

                    print(f"\n  {C.YELLOW}Transcription:{C.RESET} {user_input}\n")
                    if not user_input:
                        print(f"\n{C.RED}  ✗ Nothing captured. Try again.{C.RESET}")
                        continue
            except (EOFError, KeyboardInterrupt):
                self._quit()
                break

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                self._quit()
                break

            print()

            # Reset state for this exchange
            self._reply_ready.clear()
            self._steps.reset()
            self._current_reply = ""

            # Send to chat_loop
            payload = {
                "type": "message",
                "source": "user",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "content": user_input,
                "files": [],
                "images": [],
            }
            self.info_conn.send({"event": "message", "data": payload})

            # Spinner while waiting
            self._spinner.start("Thinking")
            self._reply_ready.wait()
            self._spinner.stop()

            # Print reply
            reply = self._current_reply
            if self.state.get_audio_mode() and reply:
                reply_tts = strip_for_tts(reply)
            print(f"\n  {C.CYAN}{C.BOLD}Iniya{C.RESET}  {C.DIM}{_ts()}{C.RESET}")
            if reply:
                for line in reply.splitlines():
                    print(f"  {line}")
                if self.state.get_audio_mode() and reply_tts:
                    self._spinner.start(f"{C.YELLOW}Synthesising audio...{C.RESET}")
                    self._audio_client.speak(reply_tts, play=True)
                    self._spinner.stop()
            else:
                print(f"  {C.DIM}(no response){C.RESET}")
            print(f"\n  {C.DIM}{'─' * 50}{C.RESET}\n")

    def _quit(self):
        print(f"\n  {C.DIM}Shutting down...{C.RESET}\n")
        self.info_conn.send({"event": "system", "data": "shutdown"})
        self._shutdown.set()


# ── Entry point (mirrors py_web.py's main signature exactly) ──
def main(info_conn=None, msg_conn=None, state=None, chatID=None, new_chat_id=None):
    if not info_conn or not msg_conn:
        print("CUI: pipe connections not provided.")
        return

    cui = CUI(info_conn, msg_conn, state, chatID, new_chat_id)
    cui.start()

    # Block until shutdown (same as webview.start() blocks in py_web.py)
    cui._shutdown.wait()

    # Tell main.py to shut down (same as py_web.py sends on window close)
    try:
        info_conn.send({"event": "system", "data": "shutdown"})
    except Exception:
        pass


if __name__ == "__main__":
    main()