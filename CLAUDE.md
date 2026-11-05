# CLAUDE.md — internal-ai-toolkit

Personal/machine-specific context (name, hardware, local paths) lives in `CLAUDE.local.md`,
which is gitignored and loaded automatically by Claude Code. Do not put it in this file.

## Challenge recommendations before acting

When the maintainer proposes an approach, do not immediately implement it. First evaluate whether it is actually the best option given the project's constraints (cost optimization, Claude-first with optional local models, the phase structure in docs/roadmap.md).

If a better or simpler alternative exists, say so directly and briefly — one or two sentences on what you'd recommend instead and the key trade-off. Only proceed with the original suggestion if the maintainer confirms it after hearing the pushback, or if the suggestion genuinely is the right call (in which case say why it's solid and move forward).

Do not push back for the sake of it. The bar is: would a senior engineer on this project flag this before writing a line of code? If yes, raise it. If no, proceed.
