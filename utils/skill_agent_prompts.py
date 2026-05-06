"""English prompt constants for Skill Agent plugin."""

# ── System Prompt Core ──────────────────────────────────────────────────────
SYSTEM_PROMPT_HEADER = """
You are a general-purpose Agent that uses Skills folders as a toolbox.

[Session Paths]
- session_dir: {session_dir}
- skills_root: {skills_root}
You must follow the progressive disclosure workflow:
1) Evaluate potential skills based only on metadata (name/description)
2) Call get_skill_metadata to read SKILL.md only when a skill is triggered
3) Before any further skill operations (list_skill_files/read_skill_file/run_skill_command), you must first call get_skill_metadata; otherwise the system will reject the call and require you to read the manual first.
4) Before executing scripts/commands, call list_skill_files to inspect the skill directory structure and ensure commands run in the correct directory.
5) Call read_skill_file only when deeper information is needed.
6) Call run_skill_command only when explicitly executing scripts/commands.
7) Before execution, confirm the skill package contains an executable entry (script/module). Do not guess module names. If missing, deliver current artifacts first and ask the user whether to create scripts in the temp directory.
8) After generating the final file per the skill instructions, mark it with export_temp_file
Path rules: uploads/ and intermediate products from write_temp_file are under session_dir; run_skill_command cwd is skills_root/<skill_name>.
Therefore: whenever command arguments reference uploads/ or temp intermediate files, always use the absolute path from read_temp_file (result.path); do not use relative paths like ../uploads or ../../temp.
Dependency install rules: for npm install/npm ci/bun install, use run_skill_command in the skill directory containing package.json (via cwd_relative). Never install in session_dir to avoid duplicate node_modules.
Supplementary rule 1: If the user request already specifies concrete types/parameters, treat as confirmed and execute directly without further questions.
Supplementary rule 2: When you need to ask the user anything: output only the question and options in this turn, then end immediately. Do not continue reading files, executing commands, or generating artifacts in the same turn.
Supplementary rule 3: Default values apply only when the user explicitly says 'default/whatever/you decide'. No reply does not equal choosing the default.
Supplementary rule 4: Before calling write_temp_file, output a "write intent confirmation" line containing: relative_path + content summary (first 80 chars) + approximate length. relative_path must be a file path (not empty, '.', '..', not ending with '/', not pointing to a directory).
{uploads_context}You must write intermediate products to the temp session directory (scripts, drafts, generated artifacts):
- Write text: write_temp_file
- Run commands to generate files: run_temp_command
For any request with a clear deliverable, you must push forward in the same turn until: generating a deliverable file, or giving a clear failure reason.
Only files marked with export_temp_file will be returned as final deliverables; uploads/ and unmarked files will not be sent back.

Available actions:
- get_session_context()
- get_skill_metadata(skill_name)
- list_skill_files(skill_name, max_depth)
- read_skill_file(skill_name, relative_path, max_chars)
- run_skill_command(skill_name, command, cwd_relative, auto_install)
- write_temp_file(relative_path, content)
- read_temp_file(relative_path, max_chars)
- list_temp_files(max_depth)
- run_temp_command(command, cwd_relative, auto_install)
- export_temp_file(temp_relative_path, workspace_relative_path, overwrite)  # does not copy, only marks deliverable name

If the model supports function call, invoke tools directly. Otherwise respond with JSON protocol:
{{"type":"tool","name":"get_skill_metadata","arguments":{{"skill_name":"xxx"}}}}
or {{"type":"final","content":"..."}}

Skill index (for determining which skills to invoke):
"""

# ── Skill Access Errors ─────────────────────────────────────────────────────
ERR_SKILL_MD_REQUIRED = (
    "Must first call get_skill_metadata(skill_name) to read SKILL.md (manual) before this tool can be used."
)
ERR_SKILL_FILES_REQUIRED = (
    "Before executing skill commands, must first call list_skill_files(skill_name) to inspect the skill directory structure."
)

# ── Skill Access Hints ──────────────────────────────────────────────────────
HINT_SKILL_MD_REQUIRED = (
    "You just attempted to call `{tool_name}` but have not yet read the SKILL.md for skill '{skill_name}'. "
    "Please call get_skill_metadata({skill_name!r}) first, then retry this tool call."
)
HINT_SKILL_FILES_REQUIRED = (
    "You just attempted to call `{tool_name}` but have not yet viewed the directory structure of skill '{skill_name}'. "
    "Please call list_skill_files({skill_name!r}) first, then retry this tool call."
)

# ── Tool Status Messages ────────────────────────────────────────────────────
TOOL_STATUS: dict[str, str] = {
    "get_skill_metadata": "Loading skill: {skill_name}...",
    "list_skill_files": "Listing files for skill: {skill_name}...",
    "read_skill_file": "Reading skill file: {skill_name}/{relative_path}...",
    "run_skill_command": "Executing command for skill: {skill_name}...",
    "write_temp_file": "Writing temp file: {relative_path}...",
    "read_temp_file": "Reading temp file: {relative_path}...",
    "list_temp_files": "Listing temp directory files...",
    "run_temp_command": "Executing temp command...",
    "export_temp_file": "Marking deliverable file: {temp_relative_path}...",
}

# ── Upload Context ──────────────────────────────────────────────────────────
UPLOADS_HEADER = ["\n\n[Uploaded Files]", "All paths are relative to this session's session_dir:"]

# ── Resume / User Interaction ───────────────────────────────────────────────
MSG_RESUME_DENIED = "Received your refusal. No scripts will be created in the temp directory for this session."
MSG_RESUME_AUTH = (
    "\n\n[Resume Authorization]\n"
    "The user has explicitly authorized you to create scripts in the temp session directory, "
    "install dependencies as needed, and continue the previous unfinished generation.\n"
    "Continue directly from intermediate artifacts in the current temp session directory, "
    "prioritizing the generation of final deliverable files.\n"
)
MSG_NO_EXECUTABLE = (
    'The skill "{skill}" requires file generation, but no executable entry was found in the skill package '
    '(e.g., script or Python module).\n'
    'The attempted entry was python -m {module}, which does not exist in the skill directory, '
    'so the target file cannot be generated.\n\n'
    'I have already generated deliverable intermediate artifacts (e.g., design philosophy .md) per the skill instructions.\n'
    'Would you allow me to create executable scripts in the temp directory and install dependencies as needed, '
    'then attempt to generate the final file?'
)

# ── Error Messages ──────────────────────────────────────────────────────────
ERR_MISSING_QUERY = "Missing query parameter"
ERR_FILE_URL = "Failed to obtain upload file URL (files[i].url)."
ERR_FILE_DOWNLOAD = "File download failed: {error}"
ERR_FILE_SAVE = "Failed to save uploaded file: {error}"
ERR_NO_SKILLS = "(No skills available)"
ERR_LLM_DNS = (
    "LLM call failed: unable to resolve model service domain (DNS/network issue).\n"
    "Error details:\n{error}\n\n"
    "Please check:\n"
    "1) Whether the plugin environment can access the public network / needs a proxy\n"
    "2) Whether DNS is working (can resolve domains like dashscope.aliyuncs.com)\n"
    "3) Whether Dify's model provider network egress is restricted"
)
ERR_LLM_FAILED = "LLM call failed:\n{error}"
ERR_MODEL_NO_TOOLS = (
    "Current model does not support Function Call. Automatically switched to JSON protocol mode.\n"
    "Some advanced features may be limited. Consider switching to a Function Call-capable model for best results.\n\n"
)
ERR_EMPTY_RESPONSE = "You did not output any content. Please continue the task: if function call is supported, invoke a tool; otherwise output JSON: {{\"type\":\"final\",\"content\":\"...\"}}"
ERR_EMPTY_REPEATED = "Model returned empty responses consecutively. No results generated."
ERR_MAX_STEPS = "Exceeded max execution steps max_steps={max_steps}. Final result not obtained."
ERR_CMD_FAILED = "Command execution failed (stderr):\n{stderr}"
ERR_STDERR = "Command failed (stderr):\n{stderr}"
ERR_UNKNOWN_TOOL = "Unknown tool: {tool_name}"

# ── Final Status Messages ───────────────────────────────────────────────────
MSG_FILES_GENERATED = "Files generated."
MSG_FILES_NO_EXPORT = "Intermediate files generated, but export_temp_file was not called to mark deliverable files."
MSG_NO_OUTPUT = "No text or file output generated."
MSG_FILES_GENERATED_SHORT = "Files generated."
MSG_INTERMEDIATE_ONLY = "Intermediate files generated, but export_temp_file was not called to mark deliverable files."
MSG_NO_OUTPUT_SHORT = "No text or file output generated."

# ── Misc ────────────────────────────────────────────────────────────────────
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant"
PROGRESS_TAG = "\n[Skill_Agent]\n"
