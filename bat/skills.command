#!/bin/bash
cd "$(dirname "$0")/.."
# Their skills, the keeper's road (SKILLS-PLAN.md) — creations/skills/<name>/
#   bat/skills.command list                 the shelf, and what waits in quarantine
#   bat/skills.command scan <name>          the scanner's verdict and findings
#   bat/skills.command approve <name>       a quarantined skill onto their shelf, after you read it
#   bat/skills.command install <source>     fetch + scan, printing the SKILL.md whole (owner/repo/path, a SKILL.md URL, a .zip URL)
#   bat/skills.command remove <name>        the folder to creations/.trash/
#   bat/skills.command browse [query]       the world's shelves (SKILL_CATALOGUES in config.py), or what matches
#   bat/skills.command browse --refresh     the same, the catalogues indexed afresh first
python3 engine/skills.py "$@"
read -n1 -r -p "(press any key to close)"
