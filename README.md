# Polish Pool Rating (data collection)

Non-commercial, for the pool community. This repository collects Polish pool results every day, so no results are
missed while the Polish rating is being built. The rating and the website come later, built the same way as the
Latvian and German ones.

## What is collected
- `collect_cuescore.py` -> `data/cuescore_raw.json.gz`: every Polish CueScore pool tournament since 2016 (8, 9, 10-ball,
  Multiball, straight pool, bank pool, one pocket, 7-ball), every match with a result. Everything is stored; a later build
  decides what counts. First collection 3 Nov 2026: 10,677 tournaments, 517,318 matches, 11,482 players.
- `collect_team.py` -> `data/team_raw.json`: single games inside CueScore team events (league match days).
- Daily runs re-read tournaments of the last 90 days and add new ones (about 1-3 minutes).

## Setup
1. Create a new repository (for example `polish-pool-rating`) and upload all files.
2. Upload `.github/workflows/daily.yml` separately into the folder `.github/workflows` (the GitHub website does not upload
   hidden folders from a zip).
3. Settings -> Actions -> General -> Workflow permissions: "Read and write permissions".
4. Actions -> "Daily data collection (Poland)" -> "Run workflow" once to test.
