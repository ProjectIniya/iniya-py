from .memory import memory_chat
from .memory.memory_static import StaticMemory
from .memory.memory_vector import VectorMemory
from .memory.memory_master import MasterMemory
from .personality import PERSONALITY, ASSISTANT_NAME
from .llm_wrapper import ask_model, preload_model, unload_all_models
from .tools.tools import ToolManager
from .text_cleaner import clean_text
from .log import log

import re, json
from pathlib import Path 
import platform
import sys

#======= HELPERS =======

def get_system_info() -> str:
    return f"""
== SYSTEM INFO ==
OS: {platform.system()} {platform.release()} ({platform.version()})
Platform: {platform.platform()}
Python: {sys.version.split()[0]}
Python executable: {sys.executable}
Shell: {"cmd.exe (Windows)" if platform.system() == "Windows" else "bash"}
""".strip()

# ================= INIT =================

BASE_PATH = Path(__file__).resolve().parent.parent

with open(BASE_PATH / "AI_Model" / "tools" / "directives" / "protocol_registry.json", "r") as f:
    registry = json.load(f)

SKILLS_DIR = Path(__file__).resolve().parent / "tools" / "skills"

SKILL_REGISTRY = {
    "coding": {
        "file": "coding.md",
        "description": "user wants to write, create, edit, run, or execute code, scripts, or files"
    },
    "search": {
        "file": "search.md",
        "description": "user wants to search the internet, find current info, or look something up"
    },
    "task": {
        "file": "task.md",
        "description": "user wants to add, list, complete, or delete a task or reminder"
    },
}

CLASSIFIER_PROMPT = """You are a task router. Given a user message, decide which skills are needed.

Available skills:
{skill_descriptions}

Rules:
- Return ONLY a valid JSON array of skill names needed, e.g. ["coding"] or ["coding", "search"] or []
- Coding: ANY mention of writing, creating, running, executing, saving code or scripts
- Search: needs live internet data, current events, or specific URLs
- Task: managing reminders or to-do items
- If nothing matches, return []

User message: "{query}"
"""

# Keywords used as fallback when the skill router LLM call produces garbage output
_CODING_HINTS = {"write", "create", "run", "execute", "script", "program", "code", "file", "make", "build", "save", "generate"}
_SEARCH_HINTS = {"search", "google", "look", "find", "latest", "current", "news", "today"}
_TASK_HINTS   = {"remind", "reminder", "task", "todo", "to-do", "schedule", "add task"}
_TRIVIAL_INPUTS = {
    "ok", "okay", "thanks", "thank you", "got it", "sure",
    "yes", "no", "cool", "great", "alright", "noted", "k",
    "hmm", "yep", "nope", "fine", "understood", "makes sense",
}


def extract_keywords(text: str):
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    common = {"and", "or", "the", "is", "my", "your", "of", "to", "with", "in", "on", "for"}
    keywords = [w for w in words if w not in common and len(w) > 3]
    return list(set(keywords))[:6]


def clean_response(text: str):
    text = text.strip()
    if text.lower().startswith(ASSISTANT_NAME.lower()):
        text = text[len(ASSISTANT_NAME):].strip(" :,-")
    return text


def make_reply(text: str, audio_mode: bool = False):
    cleaned = clean_text(text)
    return {
        "assistant": ASSISTANT_NAME,
        "text": text,
        "keywords": extract_keywords(text),
        "speak": audio_mode,
        "clean_text": cleaned if isinstance(cleaned, dict) else {"raw": text},
    }


def extract_json(raw: str) -> dict | None:
    """Strip thinking tokens / markdown and extract the JSON object."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"<\|[^|]*\|>", "", raw).strip()   # strip special tokens e.g. <|im_start|>
    raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except Exception:
        return None


# ================= AGENT =================

class BrainAgent:

    def __init__(self, chatID, audio_mode: bool = False, msgConn = None):
        log("Initializing agent...", "AGENT")

        # Memory
        self.staMem = StaticMemory(chatID)
        self.static_memory = self.staMem.load()
        self.vector_memory = VectorMemory(chatID)
        self.master_memory = MasterMemory()
        self.currentChatManager = memory_chat.CurrentChatHistory(chatID)

        # Tool runtime
        self.tool_manager = ToolManager(chatID)

        self.history = []
        self.max_history = 10
        self.audio_mode = audio_mode
        self._msgConn = msgConn
        self._system_prompt = ""   # stored so all continuation calls reuse the same prompt
        self._last_skills: list[str] = []
        self._last_mem_text: str = "No relevant memory."

        log("Agent initialized.", "AGENT")

        log("Preloading LLM model...", "AGENT")
        preload_model()

    def _check_tool_failure(self, name: str, result) -> tuple[bool, str]:
        """Returns (is_failure, reason). Catches unknown tool, ❌ prefix, status:error/blocked."""
        if isinstance(result, str):
            _lower = result.lower().lstrip()
            if result.startswith("Unknown tool:"):
                return True, result
            if result.startswith("Tool execution failed:"):
                return True, result
            # catch string-level failures from search and other tools
            if result.startswith("❌"):
                return True, result[:120]
            if _lower.startswith("search failed") or _lower.startswith("❌ search"):
                return True, result[:120]
            if "error:" in _lower[:40]:
                return True, result[:120]
            return False, ""
        if isinstance(result, dict):
            status = result.get("status", "")
            if status in ("error", "blocked"):
                return True, result.get("error") or result.get("reason") or status
            # non-zero exit code is program output, not a tool failure
        return False, ""

    def _is_trivial_followup(self, query: str) -> bool:
        """True when the message is too short/generic to need a fresh memory search."""
        words = query.strip().split()
        if len(words) > 5:
            return False
        return query.lower().strip(".,!? ") in _TRIVIAL_INPUTS or len(words) <= 2
 
    def _is_trivial_input(self, text: str) -> bool:
        """True when the text is not worth storing in vector memory."""
        words = text.strip().split()
        if len(words) > 8:
            return False
        return text.lower().strip(".,!? ") in _TRIVIAL_INPUTS


    def trim_history(self):
        if len(self.history) <= self.max_history * 2:
            return
 
        keep_count = max(6, self.max_history)
        to_summarize = [
            m for m in self.history[:-keep_count]
            if m.get("role") in ("user", "assistant")
        ]
        recent = self.history[-keep_count:]
 
        if not to_summarize:
            self.history = recent
            return
 
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}"
            for m in to_summarize
        )
        summary_prompt = (
            "Summarize this conversation in 2-3 sentences. "
            "Keep key facts, decisions, and context. Be concise.\n\n"
            + history_text
        )
 
        try:
            raw = ask_model(summary_prompt, [])
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            summary = {"role": "system", "content": f"[Earlier context] {raw}"}
            old_len = len(self.history)
            self.history = [summary] + recent
            log(f"History compressed: {old_len} turns → summary + {len(recent)} recent.", "AGENT")
        except Exception as e:
            log(f"History summarization failed ({e}), trimming.", "AGENT WARN")
            self.history = self.history[-(self.max_history * 2):]

    # ================= PROMPT =================

    def route_skills(self, query: str) -> list[str]:
        """
        Pass 1 — classify intent, return list of active skill names.
        """
        words = set(re.findall(r'\b\w+\b', query.lower()))
        active = []
        if words & _CODING_HINTS:
            active.append("coding")
        if words & _SEARCH_HINTS:
            active.append("search")
        if words & _TASK_HINTS:
            active.append("task")
        if active:
            log(f"Skill keyword → {active}", "AGENT")
        return active

    def load_skill(self, name: str) -> str:
        path = SKILLS_DIR / SKILL_REGISTRY[name]["file"]
        if path.exists():
            return path.read_text(encoding="utf-8")
        log(f"Skill file missing: {path}", "AGENT WARN")
        return ""

    
    def build_prompt(self, query: str, active_skills: list[str] = None, skip_search: bool = False):
        if skip_search:
            # reuse cached mem_text — no vector search needed for trivial follow-ups
            mem_text = self._last_mem_text
            master_text = "None"
        else:
            relevant = self.vector_memory.search_relevant(query)
            master_relevant = self.master_memory.search(query)
            mem_text = "\n".join(relevant) if relevant else "No relevant memory."
            master_text = "\n".join(master_relevant) if master_relevant else "None"
            self._last_mem_text = mem_text  # cache for trivial follow-ups
 
        prefs = self.static_memory.get("preferences", {})
        facts = self.static_memory.get("facts", [])
        pref_text = "\n".join([f"{k}: {v}" for k, v in prefs.items()]) if prefs else "None"
 
        skills_block = ""
        if active_skills:
            loaded = [self.load_skill(s) for s in active_skills]
            skills_block = "\n\n".join(loaded)
 
        return f"""
{PERSONALITY}
 
{get_system_info()}
 
== USER FACTS ==
{facts if facts else "None recorded"}
 
== USER PREFERENCES ==
{pref_text}
 
== MASTER MEMORY (cross-chat) ==
{master_text}
 
== MEMORY SEARCH ==
{mem_text}
 
== PROTOCOLS ==
{registry}
 
{f"== ACTIVE SKILLS =={chr(10)}{skills_block}" if skills_block else ""}
""".strip()

    # ================= MAIN =================

    def process(self, user_input: str):
        log(f"User: {user_input}", "AGENT")
 
        # ── Pass 1: route skills with carryover ──────────────────────
        active_skills = self.route_skills(user_input)
        is_trivial = self._is_trivial_followup(user_input)
 
        if not active_skills and self._last_skills and is_trivial:
            # short follow-up with no new intent → reuse last skill set
            active_skills = self._last_skills
            log(f"Trivial follow-up — carrying over skills: {active_skills}", "AGENT")
        else:
            self._last_skills = active_skills
 
        # ── Pass 2: build prompt (skip vector search for trivial inputs) ──
        system_prompt = self.build_prompt(user_input, active_skills, skip_search=is_trivial)
        self._system_prompt = system_prompt
        self.trim_history()
 
        self.history.append({"role": "user", "content": user_input})
        raw_reply = ask_model(self._system_prompt, self.history)
        self.history.append({"role": "assistant", "content": raw_reply})
 
        # ── initial parse ─────────────────────────────────────────────
        data = extract_json(raw_reply)
        if not data:
            log(f"Initial JSON parse failed, raw: {raw_reply[:200]}", "AGENT WARN")
            data = {
                "answer": raw_reply,
                "uncertainty": 0.5,
                "memory_add": [],
                "memory_delete": [],
                "tasks_add": [],
                "tools": [],
            }
 
        # ── Uncertainty-triggered search fallback ─────────────────────
        # If the model says it's unsure AND it isn't already doing a tool
        # call, add the search skill and re-prompt with fresh memory.
        _uncertainty = float(data.get("uncertainty", 0.3))
        if _uncertainty >= 0.65 and "search" not in active_skills and not data.get("tools"):
            log(f"Uncertainty {_uncertainty:.2f} ≥ 0.65 — adding search skill and re-prompting.", "AGENT")
            active_skills = list(active_skills) + ["search"]
            self._last_skills = active_skills
            system_prompt = self.build_prompt(user_input, active_skills, skip_search=False)
            self._system_prompt = system_prompt
            self.history.pop()                          # remove stale assistant reply
            raw_reply = ask_model(self._system_prompt, self.history)
            self.history.append({"role": "assistant", "content": raw_reply})
            parsed = extract_json(raw_reply)
            if parsed:
                data = parsed
 
        responses = []
 
        # ===== MEMORY DELETE =========================================
        for item in data.get("memory_delete", []):
            self.staMem.delete_fact(item)
            self.vector_memory.delete(item)
            responses.append(f"Memory '{item}' erased.")
            self._msgConn.send({
                "event": "message",
                "data": {"type": "memoryUpdate", "source": "agent",
                         "content": {"action": "delete", "content": item}}
            })
 
        # ===== MEMORY ADD ============================================
        for item in data.get("memory_add", []):
            self.staMem.add_fact(item)
            self.vector_memory.store_message(f"FACT: {item}")
            self._msgConn.send({
                "event": "message",
                "data": {"type": "memoryUpdate", "source": "agent",
                         "content": {"action": "add", "content": item}}
            })
 
        # ===== GLOBAL MEMORY ADD =====================================
        for item in data.get("memory_add_global", []):
            self.master_memory.store(item, source_chat_id=self.staMem.chat_id)
            self.vector_memory.store_message(f"GLOBAL FACT: {item}")
            if self._msgConn:
                self._msgConn.send({
                    "event": "message",
                    "data": {"type": "memoryUpdate", "source": "agent",
                             "content": {"action": "add_global", "content": item}}
                })
 
        # ===== GLOBAL MEMORY DELETE ==================================
        for item in data.get("memory_delete_global", []):
            self.master_memory.delete(item)
            if self._msgConn:
                self._msgConn.send({
                    "event": "message",
                    "data": {"type": "memoryUpdate", "source": "agent",
                             "content": {"action": "delete_global", "content": item}}
                })
 
        # ===== TASK ADD ==============================================
        for task in data.get("tasks_add", []):
            self.tool_manager.execute("task_add", task)
            self._msgConn.send({
                "event": "message",
                "data": {"type": "taskUpdate", "source": "agent",
                         "content": {"action": "add", "content": task}}
            })
 
        # ===== TOOL CHAIN ============================================
        MAX_TOOL_RETRIES = 3
 
        for iteration in range(8):
            used_tools = set()
 
            tools_list = data.get("tools", [])
            is_done = data.get("done", True)
 
            if is_done and not tools_list:
                if "coding" in active_skills and iteration == 0:
                    log("Coding skill active but model skipped tools — forcing tool call.", "AGENT WARN")
                    self.history.append({
                        "role": "user",
                        "content": (
                            "You described the code but did not write or run it. "
                            "For coding tasks, tools are MANDATORY — you must call them, not describe them. "
                            f"Available tools: {list(self.tool_manager.coding_protocols.keys())}. "
                            "Call file_write to create the file, then code_run to execute it. "
                            "Respond ONLY in valid JSON with tools in 'tools' and done:false."
                        )
                    })
                    raw_reply = ask_model(self._system_prompt, self.history)
                    self.history.append({"role": "assistant", "content": raw_reply})
                    parsed = extract_json(raw_reply)
                    if parsed and parsed.get("tools"):
                        data = parsed
                        continue
                    log("Force tool prompt failed, finalizing.", "AGENT WARN")
                if "search" in active_skills and iteration == 0:
                    _real_time_signals = (
                        "price", "current", "today", "latest", "now", "live",
                        "stock", "weather", "news", "status", "score", "rate",
                    )
                    query_lower = user_input.lower()
                    if any(s in query_lower for s in _real_time_signals):
                        log("Search skill active on real-time query but model skipped tools — forcing.", "AGENT WARN")
                        self.history.append({
                            "role": "user",
                            "content": (
                                "This query requires current/live data. "
                                "You MUST call web_search — do NOT answer from memory or training data. "
                                "Respond ONLY in valid JSON with web_search in 'tools' and done:false."
                            )
                        })
                        raw_reply = ask_model(self._system_prompt, self.history)
                        self.history.append({"role": "assistant", "content": raw_reply})
                        parsed = extract_json(raw_reply)
                        if parsed and parsed.get("tools"):
                            data = parsed
                            continue
                break
 
            if not tools_list:
                log("Agent not done but no tools — re-prompting.", "AGENT")
                self.history.append({
                    "role": "user",
                    "content": (
                        "You set done=false but provided no tools. "
                        "You MUST now output a tool call to continue. "
                        "Do NOT write explanations or code in 'answer'. "
                        f"Available coding tools: {list(self.tool_manager.coding_protocols.keys())}. "
                        "Respond ONLY in valid JSON with at least one tool in 'tools'."
                    )
                })
                raw_reply = ask_model(self._system_prompt, self.history)
                self.history.append({"role": "assistant", "content": raw_reply})
                parsed = extract_json(raw_reply)
 
                if parsed and "name" in parsed and "input" in parsed and "tools" not in parsed:
                    log("Re-prompt returned bare tool object — wrapping it.", "AGENT WARN")
                    parsed = {"tools": [parsed], "done": False, "answer": ""}
 
                if not parsed or not parsed.get("tools"):
                    log("Re-prompt produced no tools, finalizing.", "AGENT WARN")
                    break
                data = parsed
                continue
 
            executed = False
 
            for tool in tools_list:
                name = tool.get("name")
                tool_input = tool.get("input")
 
                if name in used_tools:
                    continue
 
                executed = True
                used_tools.add(name)
 
                result = None
                success = False
 
                for attempt in range(MAX_TOOL_RETRIES):
                    self._msgConn.send({
                        "event": "message",
                        "data": {"type": "toolUse", "source": "agent", "content": {
                            "name": name,
                            "input": tool_input,
                            "agent_reply": data.get("answer", ""),
                            "attempt": attempt + 1,
                        }}
                    })
 
                    log(f"Executing tool: {name} (attempt {attempt + 1}/{MAX_TOOL_RETRIES})", "AGENT")
                    result = self.tool_manager.execute(name, tool_input)
                    is_failure, failure_reason = self._check_tool_failure(name, result)
 
                    self._msgConn.send({
                        "event": "message",
                        "data": {"type": "toolDone", "source": "agent", "content": {
                            "name": name,
                            "result": str(result)[:500],
                            "failed": is_failure,
                        }}
                    })
 
                    if not is_failure:
                        success = True
                        self.history.append({
                            "role": "tool",
                            "content": f"{name} → {result}"
                        })
                        break
 
                    log(f"Tool {name} failed (attempt {attempt + 1}): {failure_reason}", "AGENT WARN")
 
                    if attempt + 1 >= MAX_TOOL_RETRIES:
                        log(f"Tool {name} failed after {MAX_TOOL_RETRIES} attempts. Giving up.", "AGENT WARN")
                        self._msgConn.send({
                            "event": "message",
                            "data": {"type": "toolFailed", "source": "agent", "content": {
                                "name": name,
                                "reason": failure_reason,
                                "attempts": MAX_TOOL_RETRIES,
                            }}
                        })
                        self.history.append({
                            "role": "tool",
                            "content": f"{name} → FAILED after {MAX_TOOL_RETRIES} attempts: {failure_reason}"
                        })
                        break
 
                    self.history.append({
                        "role": "user",
                        "content": (
                            f"Tool '{name}' failed with: {failure_reason}\n"
                            f"Input was: {json.dumps(tool_input)}\n"
                            f"Retry with a corrected tool call. "
                            f"Available coding tools: {list(self.tool_manager.coding_protocols.keys())}. "
                            f"Respond ONLY in valid JSON with a single corrected tool in 'tools'."
                        )
                    })
                    raw_retry = ask_model(self._system_prompt, self.history)
                    self.history.append({"role": "assistant", "content": raw_retry})
 
                    retry_data = extract_json(raw_retry)
 
                    if retry_data and "name" in retry_data and "input" in retry_data and "tools" not in retry_data:
                        log("Retry returned bare tool object — wrapping it.", "AGENT WARN")
                        retry_data = {"tools": [retry_data], "done": False, "answer": ""}
 
                    if retry_data and retry_data.get("tools"):
                        corrected = retry_data["tools"][0]
                        name = corrected.get("name", name)
                        tool_input = corrected.get("input", tool_input)
                        log(f"LLM self-corrected to: {name}", "AGENT")
                    else:
                        log("LLM failed to produce a corrected tool call.", "AGENT WARN")
                        break
 
            if not executed:
                if data.get("done", True):
                    break
 
            raw_reply = ask_model(self._system_prompt, self.history)
            self.history.append({"role": "assistant", "content": raw_reply})
 
            parsed = extract_json(raw_reply)
            if not parsed:
                log("Tool chain JSON parse failed, stopping loop", "AGENT WARN")
                data = {"tools": [], "done": data.get("done", True), "answer": data.get("answer", "")}
            else:
                data = parsed
 
        # ===== FINAL =================================================
        final_text = data.get("answer", "")
        uncertainty = float(data.get("uncertainty", 0.3))
 
        # CHANGE 5: skip trivial user inputs — don't pollute vector memory
        if not self._is_trivial_input(user_input):
            self.vector_memory.store_message(f"USER:{user_input}")
        self.vector_memory.store_message(f"{ASSISTANT_NAME}:{final_text}")
 
        final_text = clean_response(final_text)
 
        if responses:
            final_text = " ".join(responses) + "\n\n" + final_text
 
        reply = make_reply(final_text, audio_mode=self.audio_mode)
        reply["uncertainty"] = uncertainty
 
        self._msgConn.send({
            "event": "message",
            "data": {"type": "finalReply", "source": "agent", "content": reply}
        })
        return reply

    def cleanup(self):
        log("Unloading LLM model...", "AGENT")
        unload_all_models()
        log("Cleanup complete.", "AGENT")