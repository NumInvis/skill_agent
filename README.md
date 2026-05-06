## Skill Agent

**Author:** lfenghx  
**Version:** 0.0.4  
**Type:** Tool (Plugin)

### Introduction

Skill Agent is a general-purpose tool plugin based on "Skill Progressive Disclosure". It treats the local `skills/` directory as a toolbox, so the model can read the skill manual on demand, then read files / run scripts only when necessary, and finally deliver text or files.

### Use Cases

- You want to integrate Skills and constrain/strengthen the model using "manual (SKILL.md) + file structure + scripts"
- You want progress messages and to return generated files as tool outputs
- You want to package capabilities as reusable skill folders (Reference, Scripts, etc.) instead of hard-coding everything in prompts

### Features

- Progressive disclosure: skill index → read `SKILL.md` → read files / run commands as needed
- File delivery: all files in the temp session directory are returned when the agent finishes
- Free execution: the agent can execute commands such as reading/writing files and running scripts
- Controllable memory: configurable memory turns and max step depth

### Tool Parameters

This plugin provides two tools:

- **"Skill Manager"** (`tm`): manages the local skills directory (list / add / delete / download skills).
- **"Skill Agent"** (`skill_agent`): a general agent that can execute skills that have been stored. Supports file uploads, model selection, configurable max steps, memory turns and history turns.

### How to Use (in Dify)

1. Install this plugin directly from the Marketplace (or via `.difypkg`).
2. For self-hosted deployments, set `Files_url` in Dify's `.env` to your Dify address, otherwise Dify cannot fetch uploaded files.
3. Build a workflow with the **Skill Agent** tool node. Connect a model selector to the `model` parameter.
4. Use the **Skill Manager** tool to manage skills (add skill zip packs, list existing skills, etc.).
5. Chat with Skill Agent — it will automatically read skill instructions, execute commands, and deliver generated files.

Video tutorial: https://www.bilibili.com/video/BV1iszkBCEes

### Skill Standard

- Every skill must include `SKILL.md` (YAML frontmatter supported: `name`, `description`)
- `SKILL.md` can define trigger conditions, workflow, required reference reads, commands to run, and deliverable specs

### Changelog

- **0.0.4:**
  1. Fix remote-debug asset chunk blocking issue
  2. Improve tool parameter validation and error handling
  3. Strengthen path traversal protection and command whitelisting
- 0.0.3:
  1. Support agent streaming output
  2. Support interactive, multi-turn conversations across turns
  3. Support file memory (no need to re-upload repeatedly)
  4. Support running Node.js scripts as skills
  5. Improve skill_agent runtime stability
- 0.0.2: Support agent file upload and parsing; support automatic dependency installation
- 0.0.1: Implement skill management and a general agent that works with progressive disclosure

### FAQ

1. Installation issues  
   If installation fails with network access available, try switching Dify's pip mirror for better dependency download performance. In intranet environments, install via an offline package (contact the author).

2. File transfer issues  
   If uploading/downloading files fails (e.g. incorrect URL, download timeout), check whether Dify's `.env` has `Files_url` set correctly and whether it matches your Dify address.

3. No output from skill_agent  
   This is usually due to the model. Make sure your model and provider plugin support function calling. The author recommends DeepSeek-V3.1 and reports good test results.

4. Skill invocation issues  
   The more complete your skill is, the more smoothly the agent can invoke it. Ensure your skill materials and scripts are not missing. For Node.js-script skills, install a Node.js runtime in Dify's `plugin_daemon` container first.

### Author & Contact

- GitHub: lfenghx (repo: <https://github.com/lfenghx/skill_agent>)
- Bilibili: 元视界\_O凌枫o
- Email: 550916599@qq.com
