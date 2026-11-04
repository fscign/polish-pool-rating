"""German Pool Rating: collect German CueScore tournaments into data/cuescore_raw.json.

Everything is stored (decided 3 Nov 2026: gather first, decide later): every pool event held in Germany
(all disciplines, singles, doubles, handicap, any race length), every match with a result, walkovers included.
build_db.py decides what counts. Team events (league match days, CueScore type 1) are collected by collect_team.py.

First run (no 'raw_done' flag): lists every month since 2016 (one list query stops at about 9,900 results)
and fetches every pool event. Later runs: every event that started in the last DAYS days, plus new ones.
Usage: python3 collect_cuescore.py [--days 90]
"""
import json, re, sys, time, datetime, html, os, calendar
import requests
from concurrent.futures import ThreadPoolExecutor

FILE = os.environ.get('CS_FILE', 'data/cuescore_raw.json')
DAYS = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 90
TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=DAYS)
COUNTRY = os.environ.get('CS_COUNTRY', 'Germany')   # Poland collection: CS_COUNTRY=Poland
FIRST_YEAR = 2016
API = 'https://api.cuescore.com'
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (pool rating updater)', 'Accept-Language': 'en-US,en;q=0.9'})
POOL = re.compile(r'^(7|8|9|10)-Ball$|^Multiball$|^Straightpool$|^Onepocket$|^Bankpool$|^Portuguese 8-Ball$', re.I)

def get(url):
    for i in range(4):
        try:
            r = S.get(url, timeout=60); r.raise_for_status(); return r
        except Exception:
            if i == 3: raise
            time.sleep(3 * (i + 1))

log = []
def say(*a):
    msg = ' '.join(str(x) for x in a); print(msg, flush=True); log.append(msg)

import gzip
OPEN = (lambda f, m: gzip.open(f, m + 't', encoding='utf-8')) if FILE.endswith('.gz') else (lambda f, m: open(f, m, encoding='utf-8'))
cs = json.load(OPEN(FILE, 'r')) if os.path.exists(FILE) else {'tournaments': [], 'matches': [], 'players': {}}
have = {t[0] for t in cs['tournaments']}

def cs_list(a, b):
    off = 0
    while True:
        j = get(f'{API}/tournaments/?country={COUNTRY}&from={a}&to={b}&offset={off}').json()
        for it in j['items']: yield it
        if not j.get('hasMore'): break
        off = j['nextOffset']; time.sleep(0.2)

def handicap(j):
    h = j.get('handicap')
    if h and (len(h) > 0 if isinstance(h, (list, dict)) else True): return 1
    desc = html.unescape(re.sub(r'<[^>]+>', ' ', j.get('description') or ''))
    return 1 if re.search(r'handi|hcp|hendi|vorgabe', desc, re.I) else 0

def fetch(tid):
    """Tournament row:
    [id, name, start date, discipline, default race, default best-of-sets, handicap 1/0, type, city, owner, matches listed,
     matches stored, 'germany', venue/club, status, stop date]
    Match row: [tournament id, match id, player A, player B, score A, score B, race, date, round, penalty, game, best-of-sets, match status]"""
    j = get(f'{API}/tournament/?id={tid}').json()
    ms, nm = [], 0
    for m in j.get('matches') or []:
        nm += 1
        a, b = m.get('playerA') or {}, m.get('playerB') or {}
        if not a.get('playerId') or not b.get('playerId'): continue
        if m.get('matchstatus') not in ('finished', 'playing'): continue
        try: sa, sb = int(m['scoreA']), int(m['scoreB'])
        except Exception: continue
        for p in (a, b):
            pid = str(p['playerId'])
            if pid not in cs['players']:
                cc = (p.get('country') or {}).get('alpha3', '') if isinstance(p.get('country'), dict) else ''
                rep = p.get('represents'); lv = p.get('livesIn')
                cs['players'][pid] = [p.get('firstname'), p.get('lastname'), cc,
                                      (rep.get('alpha3') or rep.get('name')) if isinstance(rep, dict) else '',
                                      (lv.get('alpha3') or lv.get('name')) if isinstance(lv, dict) else '']
        ms.append([j['tournamentId'], m['matchId'], a['playerId'], b['playerId'], sa, sb, m.get('raceTo') or 0,
                   (m.get('stoptime') or m.get('starttime') or '')[:10], m.get('roundName') or '', m.get('penalty') or 0,
                   m.get('discipline') or '', m.get('bestOfSets') or 0, m.get('matchstatus') or ''])
    v = (j.get('venues') or [{}])[0] or {}
    trow = [j['tournamentId'], j['name'], (j.get('starttime') or '')[:10], j.get('discipline'), j.get('defaultRaceTo'),
            j.get('defaultBestOfSets'), handicap(j), j.get('type'), v.get('placename') or v.get('city') or '',
            (j.get('owner') or {}).get('name', ''), nm, len(ms), COUNTRY.lower(), v.get('name') or '', j.get('status') or '',
            (j.get('stoptime') or '')[:10]]
    return trow, ms

def wanted(it):
    return it.get('status') in ('Finished', 'Active') and it.get('type') != 1 and POOL.match(it.get('discipline') or '')

def run(tids, threads=6):
    def one(tid):
        for i in range(3):
            try: return tid, fetch(tid)
            except Exception: time.sleep(5)
        return tid, None
    with ThreadPoolExecutor(threads) as ex: res = list(ex.map(one, tids))
    new = upd = 0
    for tid, r in res:
        if not r: say(f'  could not read CueScore {tid}'); continue
        trow, ms = r
        cs['matches'] = [m for m in cs['matches'] if m[0] != tid] + ms
        cs['tournaments'] = [t for t in cs['tournaments'] if t[0] != tid] + [trow]
        if tid in have: upd += 1
        else: new += 1
        have.add(tid)
    return new, upd

def save():
    with OPEN(FILE + '.tmp', 'w') as f: json.dump(cs, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(FILE + '.tmp', FILE)

def backfill():
    """One-time: every German pool event since FIRST_YEAR, everything stored (re-reads events stored by the older, filtering collector)."""
    if cs.get('raw_done'): return
    todo = []
    for y in range(FIRST_YEAR, TODAY.year + 1):
        for mth in range(1, 13):
            if datetime.date(y, mth, 1) > TODAY: break
            last = calendar.monthrange(y, mth)[1]
            todo += [it['tournamentId'] for it in cs_list(f'{y}-{mth:02d}-01', f'{y}-{mth:02d}-{last}') if wanted(it)]
    todo = sorted(set(todo))
    say(f'CueScore raw backfill: {len(todo)} German pool events to read')
    for k in range(0, len(todo), 300):
        run(todo[k:k + 300]); save()
        say(f'  {min(k + 300, len(todo))}/{len(todo)}')
    cs['raw_done'] = True

def update():
    todo = []
    for it in cs_list((CUTOFF - datetime.timedelta(days=30)).isoformat(), TODAY.isoformat()):
        if not wanted(it): continue
        st = (it.get('starttime') or '')[:10]
        if it['tournamentId'] in have and st and st < CUTOFF.isoformat(): continue
        todo.append(it['tournamentId'])
    new, upd = run(todo)
    say(f'CueScore: {new} new events, {upd} recent ones re-read')

if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    backfill()
    update()
    save()
    open('update_log.txt', 'a').write('\n'.join(log) + '\n')
