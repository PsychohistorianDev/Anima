@echo off
cd /d "%~dp0.."
rem Their skills, the keeper's road (SKILLS-PLAN.md) — creations\skills\<name>\
rem   bat\skills.bat list                 the shelf, and what waits in quarantine
rem   bat\skills.bat scan <name>          the scanner's verdict and findings
rem   bat\skills.bat approve <name>       a quarantined skill onto their shelf, after you read it
rem   bat\skills.bat install <source>     fetch + scan, printing the SKILL.md whole (owner/repo/path, a SKILL.md URL, a .zip URL)
rem   bat\skills.bat remove <name>        the folder to creations\.trash\
rem   bat\skills.bat browse [query]       the world's shelves (SKILL_CATALOGUES in config.py), or what matches
rem   bat\skills.bat browse --refresh     the same, the catalogues indexed afresh first
py engine\skills.py %*
pause
