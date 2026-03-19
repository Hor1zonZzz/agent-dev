---
name: deepwiki-explorer
description: |
  Research open-source libraries and repositories using DeepWiki, then verify findings against
  locally installed Python packages. Use this skill whenever the user asks about how an open-source
  library works, how a function call chain is implemented, whether a library exposes certain APIs
  or interfaces, what design patterns exist in a library's source code, or any question that
  requires understanding the internals of a public GitHub repository. Trigger this even when the
  user doesn't mention "source code" explicitly — if they're asking "how does X work" or "does
  library Y support Z" or "what's the call chain for method A" about any open-source package,
  this skill applies. Also trigger when the user asks about architecture, extension points,
  hooks, plugin systems, or internal mechanisms of any open-source project.
---

# DeepWiki Explorer

Answer questions about open-source libraries by combining DeepWiki documentation intelligence
with local source verification against installed Python packages.

## When This Skill Applies

- "How does library X implement feature Y?"
- "What's the call chain when I call `foo.bar()`?"
- "Does library X expose an interface/hook/API for Z?"
- "How is module A designed internally?"
- "Can I extend/override behavior B in library X?"
- Any question about the internals, architecture, or source code of a public GitHub repository

## Workflow

Launch a **single subagent** that performs the following steps in serial order. The subagent
must have access to DeepWiki MCP tools and local file exploration tools (Read, Grep, Glob).

### Step 1: Identify the Repository

Determine the GitHub `owner/repo` for the library in question. Common mappings:

- PyPI package names often differ from repo names (e.g., `scikit-learn` → `scikit-learn/scikit-learn`,
  `beautifulsoup4` → `beautiful-soup-4/beautifulsoup4`)
- If unsure, use `mcp__deepwiki__ask_question` with a query like "What is the GitHub repository
  for {package_name}?" to confirm

### Step 2: Research via DeepWiki

Use DeepWiki tools in this order:

1. **`mcp__deepwiki__read_wiki_structure`** — get the documentation map for the repo to understand
   what topics are covered and find the most relevant sections
2. **`mcp__deepwiki__read_wiki_contents`** — read the specific sections that relate to the user's
   question (use the page paths from the structure response)
3. **`mcp__deepwiki__ask_question`** — ask targeted follow-up questions if the wiki contents don't
   fully answer the user's question. Frame questions specifically, e.g., "How does the Router class
   dispatch requests in repo X?" rather than vague queries

Collect from DeepWiki:
- Relevant module/file paths mentioned in the documentation
- Class and function names involved in the feature
- Architectural descriptions and design patterns
- Any API surface or extension points mentioned

### Step 3: Local Verification

Verify DeepWiki findings against the actual source code installed locally. The goal is to confirm
accuracy and catch any discrepancies due to version differences between DeepWiki's indexed version
and the locally installed version.

1. **Locate the installed package** — use the project's own Python interpreter to locate the
   package. The project interpreter is typically in `.venv/bin/python` or similar — resolve it
   the same way you would when running project code:
   ```
   <project-python> -c "import {package}; print({package}.__file__)"
   ```

2. **Verify key claims** — for each file/class/function mentioned by DeepWiki:
   - Use Grep to confirm the class or function exists at the expected location
   - Use Read to check the actual signature, parameters, and implementation outline
   - Note the exact file path and line number for each verified item

3. **Check for discrepancies** — if something DeepWiki mentions doesn't exist locally, note it
   as a potential version difference. If the local code has additional relevant APIs not mentioned
   by DeepWiki, include those too.

4. **Trace call chains** (if the user asked about call chains) — follow the actual code path:
   - Start from the entry point function
   - Use Grep to find where each subsequent function/method is called
   - Record each step with file path and line number

### Step 4: Compile Results

Return a structured summary to the main agent containing:

1. **Answer** — direct answer to the user's question
2. **Source Locations** — every relevant file path with line numbers, formatted as:
   `package/module/file.py:42` (using the full path from site-packages)
3. **Key Findings** — the verified facts, each tagged with whether it was:
   - Confirmed (DeepWiki claim matched local code)
   - Updated (local code differs from DeepWiki — include what changed)
   - Local-only (found in local code but not in DeepWiki)
4. **Version Note** — if the installed version differs from what DeepWiki describes, state both
   versions so the user knows

## Subagent Prompt Template

When spawning the subagent, use a prompt structured like this:

```
You are researching the open-source library "{library_name}" (GitHub: {owner/repo}) to answer
this question: "{user_question}"

Follow these steps in order:

1. Use mcp__deepwiki__read_wiki_structure for repo "{owner/repo}" to get the documentation map.
2. Based on the structure, use mcp__deepwiki__read_wiki_contents to read the most relevant
   sections for the question.
3. If needed, use mcp__deepwiki__ask_question to get more specific answers.
4. Locate the locally installed package using the project's Python interpreter (resolve from
   .venv/bin/python or similar):
   Run: <project-python> -c "import {import_name}; print({import_name}.__file__)"
5. Verify each file, class, and function mentioned by DeepWiki against local source:
   - Use Grep to find definitions
   - Use Read to check implementations
   - Record exact file paths and line numbers
6. If the question is about a call chain, trace it through the actual local source code.

Return your findings in this format:

## Answer
[Direct answer to the question]

## Source Locations
- [file_path:line_number] — [what this location contains]
- [file_path:line_number] — [what this location contains]

## Verification Status
- [Confirmed/Updated/Local-only]: [description of each finding]

## Version Info
- DeepWiki version: [if identifiable]
- Local version: [from package.__version__]
```

## Important Notes

- This skill only works for **public GitHub repositories** that DeepWiki can index. It will not
  work for private repositories.
- Local verification depends on the package being **installed** in the current Python environment.
  If the package is not installed, the subagent should note this and return DeepWiki findings only,
  clearly marked as unverified.
- DeepWiki may lag behind the latest release. Always trust local source code over DeepWiki when
  they conflict, and report the discrepancy.
- The subagent should use the `Explore` subagent_type or `general-purpose` subagent_type since it
  needs both MCP tools and local file access.
