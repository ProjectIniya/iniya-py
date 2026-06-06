# CODING SKILL

You have been routed here because this is a coding/scripting task.

## MANDATORY BEHAVIOR
- Asked to write code → use file_write IN THIS RESPONSE. No announcing, just do it.
- Asked to run code → use code_run IN THIS RESPONSE.
- Asked to write AND run → both tools in this response, done:false until execution completes.
- NEVER emit tools:[] for a coding task. That is a broken response.
- NEVER say "Creating the file now." with an empty tools list.

## WORKFLOW
1. file_write the script
2. code_run to execute (use 'inputs' list for stdin, never shell pipe for this)
3. done:true with the actual output in answer

## AVAILABLE TOOLS
- file_write  → { path, content, overwrite }
- file_read   → { path }
- file_list   → { path }
- file_delete → { path }
- code_run    → { path, inputs: [] }   ← PREFERRED runner
- shell_exec  → { command, cwd }       ← fallback for shell ops

## WINDOWS REMINDERS
- Use 'python' not 'python3'
- Use 'dir' not 'ls'
- Do NOT use 'echo -e'