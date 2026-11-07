"""Tournament Service (tournamentservice.net, also shown on ebc-billiard.com): every pool event of every country.

Gather everything, decide in the build (added 7 Nov 2026). Poland's POL TOUR, Best of the East and EEBC events live here,
not on CueScore. Every country is collected (rule of 6 Nov: every source except CueScore in full), so the Polish, German
and other ratings can all read the same file.

Output data/ts_raw.json.gz:
  tournaments: [id, name, date dd.mm.yy, city | club, discipline, organizer, matches stored, list country (alpha-3),
                listing status (finstand / id = folder / participants), parts of a folder [[id, title], ...]]
  matches: [tournament id, match id, player A, player B, score A, score B, race, time, round title, row class]
           (same as raw.json in the Latvian repo; a folder holds the matches of all its parts once)
  players: {Tournament Service player id: [surname, first name, country, city, birth date, sex]}
Each run: lists every country and year since 2011, reads new events and events of the last DAYS days (results change),
keeps everything else. First run reads everything (about 3,000 events).
Usage: python3 -I collect_ts.py [--days 90] [--all]
"""
import json, re, sys, os, gzip, time, datetime
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

BASE = 'https://tournamentservice.net'
FILE = os.environ.get('TS_FILE', 'data/ts_raw.json.gz')
DAYS = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 90
ALL = '--all' in sys.argv
FIRST_YEAR = 2011
TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=DAYS)
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (pool rating collector, non-commercial)', 'Accept-Language': 'en-US,en;q=0.9'})
LOG = []
def say(*a):
    m = ' '.join(str(x) for x in a); print(m, flush=True); LOG.append(m)

def req(method, url, **kw):
    for i in range(4):
        try:
            r = S.request(method, url, timeout=90, **kw); r.raise_for_status(); return r.text
        except Exception:
            if i == 3: raise
            time.sleep(5 * (i + 1))

def countries():
    """Pool country codes from the search form (the list changes when new countries join)."""
    s = BeautifulSoup(req('GET', BASE + '/tournament.php'), 'lxml')
    sel = s.find('select', attrs={'name': 'country'})
    return [o['value'] for o in sel.find_all('option') if o.get('value') and re.fullmatch(r'[A-Z]{3}', o['value'])]

def ts_list(year, country):
    h = req('POST', BASE + '/tournament.php', data={'year': str(year), 'month': '', 'disc': 'pool', 'country': country, 'city': '', 'org': ''})
    soup = BeautifulSoup(h, 'lxml'); out = []
    for tr in (soup.find('main') or soup).select('table.events tr'):
        a = tr.find('a', href=re.compile(r'tournament\.php'))
        m = a and re.search(r'(finstand|participants|id)=(\d+)', a['href'])
        if not m: continue
        td = tr.find_all('td', recursive=False)
        img = td[0].find('img') if td else None
        out.append(dict(id=int(m.group(2)), st=m.group(1), name=a.get_text(' ').strip(), date=td[2].get_text().strip() if len(td) > 2 else '',
                        place=td[4].get_text('\n').strip().replace('\n', ' | ') if len(td) > 4 else '',
                        disc=td[5].get_text().strip() if len(td) > 5 else '', org=(img.get('alt') if img else '') or '', country=country))
    return out

def ts_date(s):
    dd, mm, yy = s.split('.'); return datetime.date(2000 + int(yy), int(mm), int(dd))

def fetch_one(tid):
    """Matches and players of one event (or one folder part), same parsing as the Latvian update.py."""
    h = req('GET', f'{BASE}/embed/{tid}/finstand')
    soup = BeautifulSoup(h, 'lxml'); parts = {}
    ta = soup.find('textarea', id='participants')
    if ta and ta.get_text().strip().startswith('{'):
        for k, v in json.loads(ta.get_text()).items():
            if isinstance(v, list) and len(v) < 8: continue
            parts[k] = [v[0], v[1], v[2], v[3], v[6], v[7]] if isinstance(v, list) else [v.get('sname'), v.get('name'), v.get('country'), v.get('city'), v.get('dob'), v.get('sex')]
    else:
        m = re.search(r'participants:(\{[\s\S]*?\}),\s*\n\s*videoPlayer', h)
        if m:
            try:
                for k, v in json.loads(m.group(1)).items():
                    if v.get('sname'): parts[k] = [v['sname'], v['name'], v.get('country'), v.get('city'), v.get('dob'), v.get('sex')]
            except Exception: pass
    ms = []
    tab = soup.find(id='tab-allmatch')
    for r in (tab.select('tr[data-match]') if tab else []):
        pls = [x['data-player'] for x in r.find_all('td', recursive=False) if x.has_attr('data-player')]
        sc = [x.get_text().strip() for x in r.find_all('td', class_='c', recursive=False)]
        pr = (r.get('data-params') or '').split('×')
        ts = 0
        for idx in (7, 6, 5):
            if len(pr) > idx and pr[idx].isdigit(): ts = int(pr[idx]); break
        tds = r.find_all('td', recursive=False)
        cls = re.sub(r' ?p\d+', '', ' '.join(r.get('class', []))).strip()
        ms.append([tid, int(r['data-match']), pls[0] if pls else '', pls[1] if len(pls) > 1 else '',
                   sc[0] if sc else '', sc[1] if len(sc) > 1 else '', pr[0] if pr else '', ts, (tds[0].get('title') or '') if tds else '', cls])
    m = re.search(r'<title>(.*?)</title>', h, re.S)
    return ms, parts, (m.group(1).strip() if m else '')

def folder_kids(tid):
    h = req('GET', f'{BASE}/embed/{tid}/id?menu=f5f5f5&maximize=no')
    return [int(a) for a in dict.fromkeys(re.findall(r'<a class="evt-[a-z]+" href="(\d+)/id', h)) if int(a) != tid]

def fetch_event(t):
    """Event row + matches + players. A folder ('id' in the list) gets the matches of all its parts (each match once,
    stored under the folder id) and the list of its parts with their titles, so the build can split by game."""
    ms, parts, _ = fetch_one(t['id'])
    kids = []
    if t['st'] == 'id':
        have = {m[1] for m in ms}
        for k in folder_kids(t['id']):
            try: kms, kparts, title = fetch_one(k)
            except Exception: kids.append([k, '?']); continue
            kids.append([k, title])
            for m in kms:
                if m[1] not in have: ms.append([t['id']] + m[1:]); have.add(m[1])
            for pk, pv in kparts.items(): parts.setdefault(pk, pv)
            time.sleep(0.3)
    row = [t['id'], t['name'], t['date'], t['place'], t['disc'], t['org'], len(ms), t['country'], t['st'], kids]
    return row, ms, parts

def main():
    if os.path.exists(FILE): D = json.load(gzip.open(FILE, 'rt', encoding='utf-8'))
    else: D = {'tournaments': [], 'matches': [], 'players': {}}
    have = {t[0]: t for t in D['tournaments']}
    cc = countries()
    jobs = [(y, c) for c in cc for y in range(FIRST_YEAR, TODAY.year + 1)]
    with ThreadPoolExecutor(4) as ex: lists = list(ex.map(lambda a: ts_list(*a), jobs))
    listed = {}
    for L in lists:
        for t in L: listed.setdefault(t['id'], t)
    say(f'Tournament Service: {len(cc)} countries, {len(listed)} pool events listed')
    todo = []
    for t in listed.values():
        try: d = ts_date(t['date'])
        except Exception: d = None
        if d and d > TODAY: continue                       # not started yet
        if ALL or t['id'] not in have or (d and d >= CUTOFF) or have[t['id']][8] != t['st']: todo.append(t)
    say(f'{len(todo)} events to read ({sum(t["id"] not in have for t in todo)} new)')
    done = {}
    def work(t):
        try: return t['id'], fetch_event(t)
        except Exception as e: return t['id'], None
    with ThreadPoolExecutor(4) as ex:
        for i, (tid, res) in enumerate(ex.map(work, todo)):
            if res: done[tid] = res
            if (i + 1) % 250 == 0: say(f'  {i + 1}/{len(todo)} read')
    failed = len(todo) - len(done)
    D['matches'] = [m for m in D['matches'] if m[0] not in done]
    new = 0
    for tid, (row, ms, parts) in done.items():
        if tid not in have: new += 1
        have[tid] = row; D['matches'] += ms
        for k, p in parts.items():
            if k not in D['players'] or (not D['players'][k][2] and p[2]): D['players'][k] = p
    D['tournaments'] = sorted(have.values(), key=lambda t: t[0])
    D['collected'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    os.makedirs(os.path.dirname(FILE) or '.', exist_ok=True)
    with gzip.open(FILE, 'wt', encoding='utf-8') as f: json.dump(D, f, ensure_ascii=False, separators=(',', ':'))
    say(f'Tournament Service: {new} new events, {len(done) - new} re-read, {failed} failed; stored {len(D["tournaments"])} events, '
        f'{len(D["matches"])} matches, {len(D["players"])} players')
    with open('update_log.txt', 'a', encoding='utf-8') as f: f.write('\n'.join(LOG) + '\n')
    if failed > max(20, len(todo) // 4): sys.exit(1)

if __name__ == '__main__':
    main()
