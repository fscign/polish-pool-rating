# Polish Pool Rating (data collection: Poland and Czech Republic)

Non-commercial, for the pool community. This repository collects Polish pool results every day, so no results are
missed while the Polish rating is being built. The rating and the website come later, built the same way as the
Latvian and German ones.

## What is collected
- `collect_cuescore.py` -> `data/cuescore_raw.json.gz`: every Polish CueScore pool tournament since 2016 (8, 9, 10-ball,
  Multiball, straight pool, bank pool, one pocket, 7-ball), every match with a result. Everything is stored; a later build
  decides what counts. First collection 3 Nov 2026: 10,677 tournaments, 517,318 matches, 11,482 players.
- `collect_team.py` -> `data/team_raw.json`: single games inside CueScore team events (league match days).
- Czech Republic (added 6 Nov 2026), same scripts with CS_COUNTRY="Czech Republic": `data/cuescore_cze_raw.json.gz` and
  `data/team_cze_raw.json`.
- The German rating (fscign/german-pool-rating) copies these files every day and counts the matches of German players.
- Runs every day at 00:23 UTC (since 6 Nov 2026); re-reads tournaments of the last 90 days and adds new ones.

## Setup
1. Create a new repository (for example `polish-pool-rating`) and upload all files.
2. Upload `.github/workflows/daily.yml` separately into the folder `.github/workflows` (the GitHub website does not upload
   hidden folders from a zip).
3. Settings -> Actions -> General -> Workflow permissions: "Read and write permissions".
4. Actions -> "Daily data collection (Poland)" -> "Run workflow" once to test.
