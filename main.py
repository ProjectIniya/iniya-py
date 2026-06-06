from multiprocessing import Process, freeze_support, Queue, Pipe, Event, Manager
import threading
import time
from pathlib import Path
import sys, io
import subprocess
import argparse

from AI_Model.utils.util import lazy_import

BrainAgent_module = lazy_import("AI_Model.agent")
AudioClient_module = lazy_import("AI_Model.audio")
ChatHistory_Module = lazy_import("AI_Model.memory.memory_chat")
SharedState_Module = lazy_import("AI_Model.config")

from AI_Model.log import log, init_log_queue, log_drain_loop


import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("ddgs").setLevel(logging.WARNING)
logging.getLogger("ddgs.ddgs").setLevel(logging.WARNING)
logging.getLogger("primp").setLevel(logging.WARNING)

# ================= VENV =================

VENV_DIR = Path(".venv")
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"

if len(sys.argv) == 1 or '--cui' not in sys.argv:
    # Only redirect stdout for GUI mode — CUI needs raw stdout for input() to work
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def ensure_running_in_venv():
    if sys.prefix.endswith(str(VENV_DIR)):
        return

    if not VENV_PYTHON.exists():
        print("❌ .venv not found. Running setup...")
        subprocess.run([sys.executable, "setup.py"], check=True)

    print("🔁 Restarting inside .venv...")
    subprocess.run([str(VENV_PYTHON), *sys.argv], check=True)
    sys.exit(0)


# ================= CHAT LOOP =================

def chat_loop(state, gui_info_pipeline_conn, gui_msg_pipeline_conn, shutdown_event, main_chat_history):

    gui_info_pipeline_conn.send({"event": "system", "data": "online"})

    while not shutdown_event.is_set():
        msg = gui_info_pipeline_conn.recv()

        if msg["event"] == "system" and msg["data"] == "shutdown":
            agent.cleanup()
            shutdown_event.set()
            break

        if msg["event"] == "chatChange":
            try:
                if msg.get("chatID"):
                    if msg["chatID"] != "new" and msg["chatID"] != 'master':
                        chatInfo = main_chat_history.getChatInfo(msg["chatID"])
                        if not chatInfo:
                            log(f"Failed to get chat info for ID {msg['chatID']}", "ERROR")
                            continue
                        state.set_chat(msg["chatID"])
                    elif msg["chatID"] == "new":
                        id = main_chat_history.addNewChat(type=msg.get("type", "text"), id=msg.get("newChatID"))
                        chatInfo = main_chat_history.getChatInfo(id)
                        if not chatInfo:
                            log(f"Failed to get chat info for new chat ID {id}", "ERROR")
                            continue
                        state.set_chat(id)
                    elif msg["chatID"] == 'master':
                        if not main_chat_history.getChatInfo('master'):
                            main_chat_history.addNewChat(id='master', name='Master Chat', type='text')
                        chatInfo = main_chat_history.getChatInfo('master')
                        if not chatInfo:
                            log(f"Failed to get chat info for master chat", "ERROR")
                            continue
                        state.set_chat('master')
                    else :
                        log(f"Invalid chatID received: {msg['chatID']}", "ERROR")
                        continue
                    agent = BrainAgent_module.BrainAgent(chatID=state.get_chat(), audio_mode=chatInfo.get("type", "text"), msgConn=gui_msg_pipeline_conn)
                    chatHistory = ChatHistory_Module.CurrentChatHistory(state.get_chat())
                else:
                    id = main_chat_history.addNewChat(type=msg.get("type", "text"))
                    chatInfo = main_chat_history.getChatInfo(id)
                    if not chatInfo:
                        log(f"Failed to get chat info for new chat ID {id}", "ERROR")
                        continue
                    state.set_chat(id)
                    agent = BrainAgent_module.BrainAgent(chatID=state.get_chat(), audio_mode=chatInfo.get("type", "text"), msgConn=gui_msg_pipeline_conn)
                    chatHistory = ChatHistory_Module.CurrentChatHistory(state.get_chat())
                gui_info_pipeline_conn.send({"event": "chatChange", "status": "success", "chatID": state.get_chat()})
            except Exception as e:
                log(f"Error changing chat: {e}", "ERROR")
                continue

        if msg["event"] != "message":
            continue

        user_input = msg["data"]["content"]
        if not user_input:
            continue

        start = time.perf_counter()
        reply = agent.process(user_input)
        elapsed = time.perf_counter() - start

        try:
            log(f"Cleaned: {reply['clean_text']}", "TEXT")
        except:
            pass

        log(f"Iniya: {reply['text']}")
        log(f"Uncertainty: {reply['uncertainty']}")
        log(f" {elapsed:.2f}s\n")

        data = {
            "type": "message",
            "source": "python",
            "fullReply": reply["text"],
            "content": reply["clean_text"]["raw"],
            "timestamp": ""
        }

        chatHistory.appendMsg(msg["data"])
        chatHistory.appendMsg(data)

# ================= UTILS ================

def display_and_select_device(devices: list[dict]) -> dict | None:
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
    except ImportError:
        raise RuntimeError("pip install rich")

    console = Console()

    if not devices:
        console.print(Panel("[bold red]No usable input devices found.[/bold red]", border_style="red"))
        return None

    # ── Header ──────────────────────────────────────────────
    console.print()
    console.print(Panel(
        Text("  🎙  INPUT DEVICE SELECTOR", style="bold cyan", justify="center"),
        border_style="bright_black",
        padding=(0, 4),
    ))

    # ── Table ────────────────────────────────────────────────
    table = Table(
        box=box.ROUNDED,
        border_style="bright_black",
        header_style="bold bright_cyan",
        show_lines=True,
        padding=(0, 1),
    )

    table.add_column("#",          style="bold yellow",      justify="center", width=4)
    table.add_column("Index",      style="dim white",        justify="center", width=7)
    table.add_column("Device Name",style="bold white",       justify="left",   min_width=30)
    table.add_column("Channels",   style="bright_magenta",   justify="center", width=10)
    table.add_column("Sample Rate",style="bright_green",     justify="right",  width=13)

    for i, dev in enumerate(devices):
        table.add_row(
            f"[bold yellow]{i}[/bold yellow]",
            str(dev["index"]),
            dev["name"],
            str(dev["channels"]),
            f"{int(dev['samplerate'])} Hz",
        )

    console.print(table)
    console.print()

    # ── Selector ─────────────────────────────────────────────
    while True:
        try:
            console.print(
                f"  [dim]Enter device[/dim] [bold yellow]#[/bold yellow] "
                f"[dim](0 - {len(devices) - 1})[/dim] [dim]or[/dim] "
                f"[bold red]q[/bold red] [dim]to cancel :[/dim] ",
                end=""
            )
            raw = input().strip()

            if raw.lower() == "q":
                console.print("\n  [dim]Cancelled.[/dim]\n")
                return None

            choice = int(raw)
            if 0 <= choice < len(devices):
                selected = devices[choice]
                console.print(Panel(
                    f"[bold green]✔  Selected:[/bold green]  [bold white]{selected['name']}[/bold white]  "
                    f"[dim]({selected['channels']} ch · {int(selected['samplerate'])} Hz)[/dim]",
                    border_style="green",
                    padding=(0, 2),
                ))
                console.print()
                return selected

            console.print(f"  [red]Out of range. Pick 0 – {len(devices) - 1}[/red]")

        except ValueError:
            console.print("  [red]Not a number. Try again.[/red]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [dim]Interrupted.[/dim]\n")
            return None

# ================= MAIN =================

if __name__ == "__main__":
    ensure_running_in_venv()
    freeze_support()

    # ── Mode selection ──
    parser = argparse.ArgumentParser(description="Iniya AI Assistant")
    parser.add_argument(
        "--cui",
        action="store_true",
        help="Run in terminal (CUI) mode instead of the default GUI window"
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help="Enable audio mode (if supported by the current chat)"
    )
    parser.add_argument(
        "--chat",
        default="master",
        help="opens a specific chat by ID. Pass 'new' to create new chat"
    )
    parser.add_argument(
        "--new-chat-id",
        default="",
        help="give a custom ID for the new chat (only works if --chat new is used)"
    )
    args = parser.parse_args()

    # Shared state
    state = SharedState_Module.SharedState(manager=Manager())

    
    state.set_audio_mode(args.audio)

    if args.audio:
        selected = display_and_select_device(AudioClient_module.AudioClient.list_usable_input_devices())
        if selected:
            state.set_audio_device_index(selected["index"])
        else:
            log("No audio device selected. Continuing without audio.", "WARNING")
            sys.exit(0)
            

    if args.cui:
        from GUI.py_cui import main as gui_main
        state.set_debug_mode(mode=False)
    else:
        from GUI.py_gui import main as gui_main
        state.set_debug_mode(mode=True)

    # IPC pipes
    gui_parent_conn, gui_child_conn = Pipe()
    gui_msg_parent_conn, gui_msg_child_conn = Pipe()

    # Chat history
    main_chat_history = ChatHistory_Module.MainChatHistory()

    shutdown_event = Event()

    # Logging
    log_queue = Queue()
    init_log_queue(log_queue, state)

    log_stop_event = Event()
    log_thread = threading.Thread(
        target=log_drain_loop,
        args=(log_queue, log_stop_event),
        daemon=True
    )
    log_thread.start()

    # GUI / CUI — GUI runs as a separate Process (pywebview needs it),
    # CUI runs as a Thread since it's just stdin/stdout in the same process.
    if args.cui:
        ui_thread = threading.Thread(
            target=gui_main,
            args=(gui_child_conn, gui_msg_child_conn, state, args.chat, args.new_chat_id),
            daemon=True
        )
        ui_thread.start()
    else:
        Process(
            target=gui_main,
            args=(gui_child_conn, gui_msg_child_conn),
            daemon=True
        ).start()

    print("Systems ready.")

    # Chat thread
    threading.Thread(
        target=chat_loop,
        args=(state, gui_parent_conn, gui_msg_parent_conn, shutdown_event, main_chat_history),
        daemon=True
    ).start()

    shutdown_event.wait()
    log("Shutting down...", "SHUTDOWN")

    # Stop logging
    log_stop_event.set()
    log_thread.join(timeout=2)

    print("Shutdown complete.")