"""English prompt constants for Skill Agent plugin."""

# ── Tool Status Messages ────────────────────────────────────────────────────
TOOL_STATUS: dict[str, str] = {
    "skill": "Loading skill: {name}...",
    "read_file": "Reading file: {path}...",
    "write_file": "Writing file: {path}...",
    "bash": "Executing command...",
    "export_file": "Marking deliverable: {path}...",
}

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
    "2) Whether DNS is working\n"
    "3) Whether Dify's model provider network egress is restricted"
)
ERR_LLM_FAILED = "LLM call failed:\n{error}"
ERR_EMPTY_RESPONSE = "You did not output any content. Please continue the task: invoke a tool or provide a final answer."
ERR_EMPTY_REPEATED = "Model returned empty responses consecutively. No results generated."
ERR_MAX_STEPS = "Exceeded max execution steps max_steps={max_steps}. Final result not obtained."
ERR_CMD_FAILED = "Command execution failed (stderr):\n{stderr}"
ERR_STDERR = "Command failed (stderr):\n{stderr}"
ERR_UNKNOWN_TOOL = "Unknown tool: {tool_name}"

# ── Final Status Messages ───────────────────────────────────────────────────
MSG_FILES_GENERATED = "Files generated."
MSG_FILES_NO_EXPORT = "Intermediate files generated, but export_file was not called to mark deliverable files."
MSG_NO_OUTPUT = "No text or file output generated."
