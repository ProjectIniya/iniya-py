import json
import re
import os
import asyncio
from dotenv import load_dotenv

from AI_Model.memory.memory_tasks import TaskMemory
from AI_Model.log import log
from AI_Model.tools.directives import protocol
from AI_Model.tools.coding.coding_tools import CodingTools
from AI_Model.tools.search.searchClient import SearchClient, SearchMode


# Tools that accept a single dict argument (coding tools pattern)
_DICT_STYLE_TOOLS = {"file_write", "code_run", "shell_exec", "file_read", "file_delete"}

# Aliases — model sometimes hallucinates these names
_TOOL_ALIASES = {
    "search_web":    "web_search",
    "web_scrape":    "web_search",
    "search":        "web_search",
    "do_search":     "web_search",
    "internet_search": "web_search",
}


class ToolManager:
    def __init__(self, chatID):
        load_dotenv()
        self.task_memory = TaskMemory(chatID)
        self.chatID = chatID

        coding = CodingTools(self.chatID)
        self.coding_protocols = coding.protocols

        self._search_client = SearchClient(
            tavily_key=os.getenv("TAVILY_API_KEY") or None,
        )

        # Tool registry (per-instance)
        self.tools = {
            **coding.get_tools(),
            "web_search": self.web_search,

            "task_add":      self.task_memory.add_task,
            "task_list":     self.task_memory.list_tasks,
            "task_complete": self.task_memory.complete_task,
            "task_delete":   self.task_memory.delete_task,

            "execute_protocol": protocol.execute_protocol_by_code,
        }

    # ================= WEB SEARCH =================

    def web_search(self, query: str, mode: str = "normal", max_results: int = 5) -> str:
        log(f"🔍 Search [{mode}]: {query}", "TOOLS")

        client = SearchClient(
            tavily_key=os.getenv("TAVILY_API_KEY") or None,
            max_results=max_results,
        )

        try:
            result = asyncio.run(
                client.search(query, mode=SearchMode(mode.lower()))
            )
        except Exception as e:
            log(f"Search error: {e}", "TOOLS")
            return f"❌ Search failed: {e}"

        results = result.get("results", [])

        if not results:
            return "No results found."

        lines = []
        for i, r in enumerate(results, 1):
            content = (r.extracted_content or r.content or "").strip()
            snippet = content[:400] + "..." if len(content) > 400 else content
            lines.append(f"[{i}] {r.title}\n{r.url}\n{snippet}")

        return "\n\n".join(lines)

    # ================= TOOL CALL PARSER =================

    @staticmethod
    def parse_tool_call(text: str):
        match = re.search(r"\{.*?\}", text.strip(), re.DOTALL)
        if not match:
            return None, None
        try:
            data = json.loads(match.group(0))
            return data.get("action"), data.get("input")
        except Exception:
            return None, None

    # ================= EXECUTE TOOL =================

    def execute(self, action: str, tool_input):
        # resolve aliases first
        action = _TOOL_ALIASES.get(action, action)

        tool = self.tools.get(action)
        if not tool:
            return f"Unknown tool: {action}"

        try:
            if tool_input is None:
                return tool()
            elif isinstance(tool_input, dict):
                if action in _DICT_STYLE_TOOLS:
                    # coding tools expect the whole dict as one arg
                    return tool(tool_input)
                else:
                    # everything else (web_search, task_*, etc.) uses **kwargs
                    return tool(**tool_input)
            else:
                return tool(tool_input)
        except Exception as e:
            log(f"Tool error [{action}]: {e}", "TOOLS")
            return f"Tool execution failed: {e}"