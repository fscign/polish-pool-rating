"""German Pool Rating: singles inside CueScore team events (league match days, team cups).

Decided by Aleksandrs 3 Nov 2026: individual player-vs-player matches inside team events count; doubles don't.
CueScore's API gives only team-vs-team results, so for every team match the individual matches are read from
https://cuescore.com/ajax/match/matchDetails.php (names, flags, discipline, race, score) and the player names are
matched to CueScore player ids through the two teams' roster pages (https://cuescore.com/team/x/<teamId>).

Output: data/team_raw.json = {"tournaments": [...], "matches": [...], "players": {...}, "rosters": {...}, "done": [...]}
in the same row format as cuescore_raw.json, plus column 11 = match type ('0' singles, '2' doubles) and column 12 = raw names
for doubles. Everything is stored (gather first, decide in build_db.py); events whose first team match has no singles
(pair tournaments) are not read further, because they hold no player-vs-player results.
"""
import json, re, os, sys, time, html, datetime, calendar
import requests
from concurrent.futures import ThreadPoolExecutor

API = 'https://api.cuescore.com'
WEB = 'https://cuescore.com'
COUNTRY = os.environ.get('CS_COUNTRY', 'Germany')
DAYS = 90
TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=DAYS)
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (pool rating updater)', 'Accept-Language': 'en-US,en;q=0.9'})
DISC = {'2': '8-Ball', '3': '9-Ball', '4': '10-Ball', '10': 'Multiball'}
PLACEHOLDER = re.compile(r'ersatz|spieler\s*\d|player\s*\d|n\.?\s*n\.?$|^\s*-+\s*$|unbekannt|freilos|bye', re.I)

def get(url):
    for i in range(4):
        try:
            r = S.get(url, timeout=60); r.raise_for_status(); return r
        except Exception:
            if i == 3: raise
            time.sleep(3 * (i + 1))

FILE = 'data/team_raw.json'
T = json.load(open(FILE, encoding='utf-8')) if os.path.exists(FILE) else \
    {'tournaments': [], 'matches': [], 'players': {}, 'rosters': {}, 'done': []}
done = set(T['done'])

def norm(n):
    return re.sub(r'\s+', ' ', html.unescape(n or '')).strip().lower()

def roster(team_id):
    k = str(team_id)
    if k in T['rosters']: return T['rosters'][k]
    h = get(f'{WEB}/team/x/{team_id}').text
    out = {}
    for slug, pid in re.findall(r'/player/([^"/]+)/(\d+)"', h):
        name = requests.utils.unquote(slug.replace('+', ' '))
        out.setdefault(norm(name), pid)
    T['rosters'][k] = out
    return out

TD = re.compile(r'<tr id="match-(\d+)" class="match ([^"]*)"([^>]*)>(.*?)</tr>', re.S)
def attr(a, name):
    m = re.search(name + r'="([^"]*)"', a); return m.group(1) if m else ''
def side(cell_html):
    nm = re.search(r'<div class="name[^"]*">(.*?)</div>', cell_html, re.S)
    fl = re.search(r'<img class="flag"[^>]*alt="([^"]*)"', cell_html)
    return (html.unescape(nm.group(1)).strip() if nm else ''), (fl.group(1) if fl else '')

def individual(tid, team_match_id):
    h = get(f'{WEB}/ajax/match/matchDetails.php?tournamentId={tid}&id={team_match_id}').text
    out = []
    for mid, cls, attrs, body in TD.findall(h):
        if 'data-parent-id' not in attrs: continue
        mtype = attr(attrs, 'data-match-type'); disc = attr(attrs, 'data-discipline')
        race = int(attr(attrs, 'data-race-to') or 0); start = attr(attrs, 'data-starttime')[:10]
        cells = dict(re.findall(r'<td class="(playerA|playerB)"[^>]*>(.*?)</td>', body, re.S))
        sa = re.search(r'<td class="scoreA[^"]*">.*?value="(-?\d*)"', body, re.S)
        sb = re.search(r'<td class="scoreB[^"]*">.*?value="(-?\d*)"', body, re.S)
        na, ca = side(cells.get('playerA', '')); nb, cb = side(cells.get('playerB', ''))
        out.append(dict(mid=int(mid), finished='finished' in cls, mtype=mtype, disc=DISC.get(disc, disc), race=race, date=start,
                        a=na, ca=ca, b=nb, cb=cb, sa=sa.group(1) if sa else '', sb=sb.group(1) if sb else ''))
    return out

CC = {'Germany': 'DEU', 'Austria': 'AUT', 'Switzerland': 'CHE', 'Netherlands': 'NLD', 'Poland': 'POL', 'Turkey': 'TUR', 'Türkiye': 'TUR',
      'Italy': 'ITA', 'Greece': 'GRC', 'Croatia': 'HRV', 'Serbia': 'SRB', 'Russia': 'RUS', 'Ukraine': 'UKR', 'France': 'FRA', 'Vietnam': 'VNM',
      'Viet Nam': 'VNM', 'United Kingdom': 'GBR', 'England': 'GBR', 'Bosnia and Herzegovina': 'BIH', 'Kosovo': 'XKX', 'Albania': 'ALB',
      'Spain': 'ESP', 'Portugal': 'PRT', 'Romania': 'ROU', 'Hungary': 'HUN', 'Czech Republic': 'CZE', 'Czechia': 'CZE', 'Thailand': 'THA',
      'Philippines': 'PHL', 'Iran': 'IRN', 'Iraq': 'IRQ', 'Syria': 'SYR', 'Afghanistan': 'AFG', 'Kazakhstan': 'KAZ', 'Lebanon': 'LBN',
      'Latvia': 'LVA', 'Lithuania': 'LTU', 'Estonia': 'EST', 'Denmark': 'DNK', 'Belgium': 'BEL', 'Luxembourg': 'LUX', 'Sweden': 'SWE',
      'Norway': 'NOR', 'Finland': 'FIN', 'United States': 'USA', 'China': 'CHN', 'Morocco': 'MAR', 'Tunisia': 'TUN', 'Slovakia': 'SVK',
      'Slovenia': 'SVN', 'North Macedonia': 'MKD', 'Bulgaria': 'BGR', 'Montenegro': 'MNE', 'Moldova': 'MDA', 'Georgia': 'GEO', 'Armenia': 'ARM'}

def fetch_event(tid):
    j = get(f'{API}/tournament/?id={tid}').json()
    if j.get('status') not in ('Finished', 'Active'): return None
    rows, players, unmatched, doubles, nm = [], {}, 0, 0, 0
    checked = 0
    for m in j.get('matches') or []:
        a, b = m.get('playerA') or {}, m.get('playerB') or {}
        if not a.get('teamId') or not b.get('teamId'): continue
        if m.get('matchstatus') != 'finished': continue
        ind = individual(tid, m['matchId']); checked += 1
        if checked == 1 and not any(x['mtype'] == '0' for x in ind): break   # doubles / pairs event: no singles inside
        try: ra, rb = roster(a['teamId']), roster(b['teamId'])
        except Exception: ra, rb = {}, {}
        for x in ind:
            nm += 1
            if not x['finished'] or not x['a'] or not x['b']: continue
            if x['mtype'] != '0':   # doubles: stored with the raw pair names, not rated
                doubles += 1
                try: rows.append([tid, x['mid'], '', '', int(x['sa']), int(x['sb']), x['race'], x['date'] or (j.get('starttime') or '')[:10],
                                  m.get('roundName') or '', 0, x['disc'], x['mtype'], x['a'] + ' | ' + x['b']])
                except ValueError: pass
                continue
            if PLACEHOLDER.search(x['a']) or PLACEHOLDER.search(x['b']): continue
            ids = []
            for name, cc, ros, other in ((x['a'], x['ca'], ra, rb), (x['b'], x['cb'], rb, ra)):
                pid = ros.get(norm(name)) or other.get(norm(name))
                if not pid: unmatched += 1; pid = 'n:' + norm(name)     # no roster match: kept by name, merged by name later
                ids.append(pid)
                if pid not in players:
                    w = name.split(); players[pid] = [' '.join(w[:-1]), w[-1] if w else '', CC.get(cc, ''), '', '']
            try: sa, sb = int(x['sa']), int(x['sb'])
            except ValueError: continue
            rows.append([tid, x['mid'], ids[0], ids[1], sa, sb, x['race'], x['date'] or (j.get('starttime') or '')[:10],
                         m.get('roundName') or '', 0, x['disc'], '0', ''])
    v = (j.get('venues') or [{}])[0] or {}
    trow = [tid, j['name'], (j.get('starttime') or '')[:10], j.get('discipline'), j.get('defaultRaceTo'), 0, 0, j.get('type'),
            v.get('placename') or '', (j.get('owner') or {}).get('name', ''), nm, len(rows), 'germany', v.get('name') or '', 'team']
    return trow, rows, players, unmatched, doubles

def team_events(a, b):
    off = 0
    while True:
        jj = get(f'{API}/tournaments/?country={COUNTRY}&from={a}&to={b}&offset={off}').json()
        for it in jj['items']:
            if it.get('type') == 1 and re.fullmatch(r'(8|9|10)-Ball|Multiball', it.get('discipline') or '') and it.get('status') in ('Finished', 'Active') \
               and not re.search(r'doppel|double|scotch|\bduo\b|\bpaar|pärchen|pairs?\b', it['name'], re.I):   # pair tournaments: no singles inside
                yield it
        if not jj.get('hasMore'): break
        off = jj['nextOffset']; time.sleep(0.2)

def run(tids, threads=8):
    def one(tid):
        for i in range(3):
            try: return tid, fetch_event(tid)
            except Exception: time.sleep(5)
        return tid, 'error'
    with ThreadPoolExecutor(threads) as ex: res = list(ex.map(one, tids))
    stats = [0, 0, 0, 0]
    for tid, r in res:
        if r in (None, 'error'):
            if r is None: T['done'].append(tid)
            continue
        trow, rows, players, unm, dbl = r
        T['matches'] = [m for m in T['matches'] if m[0] != tid] + rows
        T['tournaments'] = [t for t in T['tournaments'] if t[0] != tid] + ([trow] if rows else [])
        for k, v in players.items(): T['players'].setdefault(str(k), v)
        if trow[2] < CUTOFF.isoformat(): T['done'].append(tid)
        stats[0] += 1; stats[1] += len(rows); stats[2] += unm; stats[3] += dbl
    return stats

if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    if not T.get('backfill_done'):
        tids = []
        for y in range(2016, TODAY.year + 1):
            for mth in range(1, 13):
                if datetime.date(y, mth, 1) > TODAY: break
                last = calendar.monthrange(y, mth)[1]
                tids += [it['tournamentId'] for it in team_events(f'{y}-{mth:02d}-01', f'{y}-{mth:02d}-{last}')]
        a = (CUTOFF - datetime.timedelta(days=30)).isoformat()
    else:
        a = (CUTOFF - datetime.timedelta(days=30)).isoformat()
        tids = [it['tournamentId'] for it in team_events(a, TODAY.isoformat())]
    tids = sorted(set(tids) - done)
    print('team events to read:', len(tids), flush=True)
    for k in range(0, len(tids), 50):
        st = run(tids[k:k + 50])
        json.dump(T, open(FILE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'  {min(k + 50, len(tids))}/{len(tids)}: events {st[0]}, singles {st[1]}, names without roster match {st[2]}, doubles skipped {st[3]}', flush=True)
    T['backfill_done'] = True
    json.dump(T, open(FILE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
