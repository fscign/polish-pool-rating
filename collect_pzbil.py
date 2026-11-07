"""pzbil.pl (Polski Związek Bilardowy): the federation's own tournaments and the Polish team league (added 7 Nov 2026).

Gather everything, decide in the build. Only reachable from GitHub (Claude's workspace is blocked); robots.txt allows all.

1. Tournaments: https://pzbil.pl/tournament/index (about 860 events since 2008: Polish Championships, Junior Tour,
   junior / youth / school championships, Women's Polish Cup, disabled players, Heyball ...). Each event's bracket
   (tournament/view?id=N) gives every match with player ids and scores; the start list (tournament/players?id=N) gives
   full names and clubs.
2. League since 2025 (new system): pzbil.pl/liga/<league>/info/matches/?season_id=S&group=G -> team matches,
   info/games/?match_id=M -> every game (8-ball / 10-ball singles, 9-ball doubles ...). Final stages via final-games.
3. League archive 2011-2024 (old system): archiwum.pzbil.pl/liga/<year>/terminarz_*.php, zespoly_2liga.php,
   baraze2liga.php -> wyniki_*_ind.php pages with every game. 2008-2010 exist only as PDFs with team scores (skipped).

Output data/pzbil_raw.json.gz:
  tournaments: [id, name, date from (yyyy-mm-dd), date to, kind ('tournament' / 'league'), game ('8-ball' ... or ''),
                status, url, extra]
      ids: 'T<n>' tournament, 'L<match id>' league match (new system), 'A<year>:<page>:<round>:<match>' archive match
  matches: [tournament id, number in event, player A, player B, score A, score B, game, round, date, status]
      players are pzbil.pl player ids ('/zawodnicy/<id>/'; the archive uses the same ids); doubles are 'id1+id2';
      a missing player is ''. Scores are strings as shown.
  players: {id: [first name, surname, club]}
Each run reads new tournaments, tournaments of the last DAYS days or not finished, the current league seasons, and the
archive once (flag archive_done = 3), then only retries archive pages that failed. Usage: python3 -I collect_pzbil.py [--days 60] [--all]
"""
import json, re, sys, os, gzip, time, datetime, html as H
import requests
from bs4 import BeautifulSoup

BASE = 'https://pzbil.pl'
ARCH = 'https://archiwum.pzbil.pl'
FILE = os.environ.get('PZBIL_FILE', 'data/pzbil_raw.json.gz')
DAYS = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 60
ALL = '--all' in sys.argv
TODAY = datetime.date.today()
CUTOFF = (TODAY - datetime.timedelta(days=DAYS)).isoformat()
PAUSE = 0.4
RETRY_CAP = 150   # failed archive match pages retried per run (they take turns, oldest failures first)
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (pool rating collector, non-commercial)', 'Accept-Language': 'pl,en;q=0.8'})
LOG = []
def say(*a):
    m = ' '.join(str(x) for x in a); print(m, flush=True); LOG.append(m)

def get(url):
    for i in range(4):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 404: return ''
            if r.status_code >= 500 and i >= 1: r.raise_for_status()   # one retry only: these errors stay
            r.raise_for_status(); time.sleep(PAUSE)
            b = r.content
            try: return b.decode('utf-8')
            except UnicodeDecodeError:
                t = b.decode('utf-8', 'replace')
                return t if t.count('�') < 20 else b.decode('cp1250', 'replace')
        except Exception as e:
            if i == 3 or ('Server Error' in str(e) and i >= 1): raise
            time.sleep(3 * (i + 1))

def get_or_empty(url):
    """pzbil.pl sometimes answers 500 for single pages: skip them (they are tried again next run)."""
    try: return get(url)
    except Exception as e: say('  skipped', url, repr(e)[:80]); return ''

def soup(h): return BeautifulSoup(h, 'lxml')
def txt(x): return re.sub(r'\s+', ' ', H.unescape(x.get_text(' ') if hasattr(x, 'get_text') else str(x))).replace('\xa0', ' ').strip()
def pid(a):
    m = a and re.search(r'/zawodnicy/(\d+)/|[?&]id=(\d+)', a.get('href', ''))
    return (m.group(1) or m.group(2)) if m else ''
def game_of(s):
    s = (s or '').lower()
    for g in ('10', '9', '8'):
        if re.search(rf'\b{g}\s*-?\s*(bil|ball)', s): return f'{g}-ball'
    if re.search(r'14\s*/\s*1|14\+1|14\.1', s): return '14.1'
    if 'heyball' in s: return 'heyball'
    return ''

D = {'tournaments': [], 'matches': [], 'players': {}}
if os.path.exists(FILE): D = json.load(gzip.open(FILE, 'rt', encoding='utf-8'))
TOUR = {t[0]: t for t in D['tournaments']}
DEBUG = []   # result pages the bracket parser could not read (round-robin groups?), saved to data/pzbil_debug/ for checking
def store(row, ms, players):
    TOUR[row[0]] = row
    D['matches'] = [m for m in D['matches'] if m[0] != row[0]] + ms
    for k, v in players.items():
        if k and (k not in D['players'] or (v[0] and len(' '.join(v[:2])) > len(' '.join(D['players'][k][:2])))): D['players'][k] = v
def add_player(P, a, club=''):
    """Player from a link: the visible name may be shortened ('M. Kalina'); the start list gives the full name."""
    k = pid(a)
    if not k: return ''
    nm = txt(a).split(' ')
    if k not in P and k not in D['players']: P[k] = [' '.join(nm[:-1]), nm[-1] if nm else '', club]
    return k

# ---------------------------------------------------------------- 1. tournaments
def tournament_list():
    out, page = [], 1
    while True:
        s = soup(get(f'{BASE}/tournament/index?page={page}'))
        rows = s.select('tr[data-key]')
        if not rows: break
        for tr in rows:
            td = tr.find_all('td', recursive=False)
            if len(td) < 6: continue
            d = re.findall(r'\d{4}-\d{2}-\d{2}', txt(td[1]))
            st = td[5].find(attrs={'title': True})
            out.append(dict(id=int(tr['data-key']), name=txt(td[0]), d1=d[0] if d else '', d2=d[-1] if d else '',
                            results=bool(td[3].find('a')), status=st['title'] if st else ''))
        last = max([int(x) for x in re.findall(r'[?&]page=(\d+)', str(s.select_one('.pagination') or ''))] or [page])
        if page >= last: break
        page += 1
    return out

def fetch_tournament(t):
    tid = f"T{t['id']}"; P = {}
    # start list: full names and clubs
    for tr in soup(get_or_empty(f"{BASE}/tournament/players?id={t['id']}")).select('tr[data-key]'):
        a = tr.find('a', href=re.compile('/zawodnicy/'))
        if not a: continue
        c = tr.find('a', href=re.compile('/kluby/'))
        nm = txt(a).split(' ')
        P[pid(a)] = [' '.join(nm[:-1]), nm[-1], txt(c) if c else '']
    ms = []
    if t['results']:
        s = soup(get(f"{BASE}/tournament/view?id={t['id']}"))
        sub = s.select_one('.tc-main-post-title h3')
        for n, tab in enumerate(s.select('table.tabela_main'), 1):
            rows = tab.find_all('tr')
            if len(rows) < 2: continue
            side = []
            for r in rows[:2]:
                a = r.find('a', href=re.compile('/zawodnicy/')); tds = r.find_all('td')
                side.append((add_player(P, a) if a else '', txt(tds[-1]) if tds else '', bool(r.find('b'))))
            if not side[0][0] and not side[1][0]: continue
            # round: nearest heading or lettered section above (kept as found; brackets have no match numbers)
            ms.append([tid, n, side[0][0], side[1][0], side[0][1], side[1][1], game_of(t['name'] + ' ' + (txt(sub) if sub else '')), '', t['d1'], 'W1' if side[0][2] else 'W2' if side[1][2] else ''])
        if not ms and len(DEBUG) < 5 and s.select_one('main table, main iframe'): DEBUG.append((tid, str(s)))
    row = [tid, t['name'], t['d1'], t['d2'], 'tournament', game_of(t['name']), t['status'], f"{BASE}/tournament/view?id={t['id']}", {}]
    return row, ms, P

# ---------------------------------------------------------------- 2. league, new system (2025 onwards)
SLUGS = ['bilardowa-ekstraklasa', '1-liga-bilardowa', '2-liga-bilardowa', '3-liga-bilardowa']
def games_page(url, tid, date, rnd, name, extra):
    s = soup(get(url)); P = {}; ms = []
    for n, box in enumerate(s.select('#games-list > div'), 1):
        head = box.select_one('.border-bottom'); label = txt(head) if head else ''
        cols = box.select('.row > div')
        if len(cols) < 3: continue
        a_side = [add_player(P, a) for a in cols[0].find_all('a', href=re.compile('/zawodnicy/'))]
        b_side = [add_player(P, a) for a in cols[2].find_all('a', href=re.compile('/zawodnicy/'))]
        sc = [txt(x) for x in cols[1].select('span')]
        stt = box.find_all('div', recursive=True)[-1]
        ms.append([tid, n, '+'.join(a_side), '+'.join(b_side), sc[0] if sc else '', sc[1] if len(sc) > 1 else '',
                   game_of(label) or label, rnd + (' debel' if 'debel' in label.lower() else ''), date, txt(stt)])
    t4 = s.select_one('.section-title-style8 h4')
    if t4: extra = dict(extra, title=txt(t4))
    row = [tid, (txt(t4) + ': ' if t4 else '') + name, date, date, 'league', '', 'finished' if ms and all('zakończ' in m[9] for m in ms) else 'open', url, extra]
    return row, ms, P

def league_new():
    n_m = 0; done_seasons = set()
    for slug in SLUGS:
        seasons = set()
        info = get_or_empty(f'{BASE}/liga/{slug}/info/')
        seasons |= {(int(x), 0) for x in re.findall(r'season_id=(\d+)', info)}
        for sid in range(1, 21):          # past seasons are only reachable by number
            h = get_or_empty(f'{BASE}/liga/{slug}/info/archive?season_id={sid}')
            if f'season_id={sid}' in h and re.search(rf'/liga/{slug}/info/(matches|final-games)', h): seasons.add((sid, 1))
        for sid, arch in sorted(seasons):
            if sid in done_seasons: continue
            done_seasons.add(sid)
            title = ''
            for g in range(1, 16):
                h = get_or_empty(f'{BASE}/liga/{slug}/info/matches/?season_id={sid}&group={g}&archive={arch}')
                s = soup(h)
                title = title or txt(s.select_one('h4') or '')
                found = 0
                for box in s.select('.cat-box'):
                    rnd = txt(box.select_one('h4') or '')
                    for tr in box.select('tr[data-key]'):
                        a = tr.find('a', href=re.compile(r'games/\?match_id='))
                        if not a: continue
                        found += 1
                        mid = re.search(r'match_id=(\d+)', a['href']).group(1); tid = f'L{mid}'
                        td = tr.find_all('td', recursive=False)
                        date = (re.findall(r'\d{4}-\d{2}-\d{2}', txt(td[0])) or [''])[0]
                        if tid in TOUR and TOUR[tid][6] == 'finished' and not ALL and date < CUTOFF and 'title' in TOUR[tid][8]: continue
                        teams = [txt(x) for x in tr.select('a[href*="/kluby/"]')]
                        res = store_new(BASE + H.unescape(a['href']), tid, date, rnd, f"{slug} season {sid} group {g}: {' - '.join(teams)}",
                                        {'league': slug, 'season': sid, 'group': g, 'teams': teams})
                        n_m += res
                if not found: break
            # final stages (play-off)
            h = get_or_empty(f'{BASE}/liga/{slug}/info/archive?season_id={sid}') if arch else info
            for mid in sorted(set(re.findall(r'final-games/\?match_id=(\d+)', h)), key=int):
                tid = f'LF{slug[:2]}{sid}-{mid}'
                if tid in TOUR and not ALL: continue
                n_m += store_new(f'{BASE}/liga/{slug}/info/final-games/?match_id={mid}&archive={arch}', tid, '', 'final', f'{slug} season {sid} final stage {mid}',
                                 {'league': slug, 'season': sid, 'final': True})
    say(f'pzbil.pl league (2025+): {n_m} games stored')

def store_new(url, tid, date, rnd, name, extra):
    try: row, ms, P = games_page(url, tid, date, rnd, name, extra)
    except Exception as e: say('  failed', url, repr(e)[:120]); return 0
    store(row, ms, P); return len(ms)

# ---------------------------------------------------------------- 3. league archive 2011-2024
PL_MONTH = {'stycz': 1, 'lut': 2, 'mar': 3, 'kwie': 4, 'maj': 5, 'czerw': 6, 'lip': 7, 'sierp': 8, 'wrze': 9, 'pa': 10, 'listop': 11, 'grud': 12}
def pl_date(s, year):
    m = re.search(r'(\d{1,2})\s+([a-ząćęłńóśźż]+)', s.lower())
    if not m: return ''
    for k, v in PL_MONTH.items():
        if m.group(2).startswith(k): return f'{year}-{v:02d}-{int(m.group(1)):02d}'
    return ''

def archive():
    """League archive 2011-2024. A full pass reads every schedule page (stored team matches are skipped) and records the
    pages that answered with an error in D['archive_failed'] (schedule pages: [year, page]) and D['archive_failed_games']
    ([year, link, date]). After a full pass (archive_done = 3) each run only retries those failed pages: pzbil.pl's
    archive often answers 500, and a page that works later fills the gap (e.g. I liga 2023-2024)."""
    full = ALL or D.get('archive_done') != 3
    if full:
        idx = get_or_empty(f'{BASE}/page/polska-liga-bilardowa-archiwum/')
        if not idx: return
        starts = [[int(y), p] for y, p in sorted(set(re.findall(r'https://archiwum\.pzbil\.pl/liga/(\d{4})/([a-z_0-9]+\.php(?:\?[^"\']*)?)', idx)))]
        retry_games = []
    else:
        starts = D.get('archive_failed', [])
        retry_games = D.get('archive_failed_games', [])
        if not starts and not retry_games: return
    failed_pages, failed_games = [], []
    n_m = 0; seen_pages = set(); seen_games = set()
    games = [(y, l, d) for y, l, d in retry_games]
    for year, start in starts:
        queue = [start]; dates = {}
        while queue:
            page = H.unescape(queue.pop(0))
            if (year, page) in seen_pages: continue          # page names repeat every year: remember them per year
            seen_pages.add((year, page))
            try: h = get(f'{ARCH}/liga/{year}/{page}')
            except Exception as e: say('  failed', year, page, repr(e)[:100]); failed_pages.append([year, page]); continue
            # remember the date of each round on this schedule page: header "1 kolejka - 14 lutego" before the links
            cur = ''
            for tok in re.finditer(r'(\d+)(?:&nbsp;|\s)+kolejka(?:&nbsp;|\s|-)+(?:&nbsp;)?([^<]*)|href="(wyniki_[a-z0-9_]*ind[a-z0-9_]*\.php\?[^"]+)"', h):
                if tok.group(1): cur = pl_date(H.unescape(tok.group(2) or ''), year)
                else: dates.setdefault(H.unescape(tok.group(3)), cur)
            for link in re.findall(r'href="((?:terminarz|zespoly|baraze|tabela_grupy|grupa)[a-z0-9_]*\.php(?:\?[^"]*)?)"', h):
                if (year, H.unescape(link)) not in seen_pages: queue.append(link)
        games += [(year, l, d) for l, d in dates.items()]
    tries = 0; waiting = []
    for year, link, date in games:
        if (year, link) in seen_games: continue
        if not full and tries >= RETRY_CAP: waiting.append([year, link, date]); continue   # rest waits for the next run
        tries += 1
        seen_games.add((year, link))
        q = dict(re.findall(r'(\w+)=([^&]+)', link))
        tid = f"A{year}:{link.split('.php')[0]}:{':'.join(f'{k}{v}' for k, v in q.items())}"
        if tid in TOUR and not ALL: continue
        if len(seen_games) % 200 == 0: save()
        try: n_m += archive_match(f'{ARCH}/liga/{year}/{link}', tid, date, year)
        except Exception as e: say('  failed', year, link, repr(e)[:100]); failed_games.append([year, link, date])
    D['archive_failed'] = failed_pages; D['archive_failed_games'] = waiting + failed_games   # untried first next time
    if full: D['archive_done'] = 3
    say(f'pzbil.pl league archive ({"full pass" if full else "retry of failed pages"}): {n_m} games stored, '
        f'still failing {len(failed_pages)} schedule pages and {len(failed_games)} match pages')

def archive_match(url, tid, date, year):
    s = soup(get(url)); P = {}; ms = []
    title = txt(s.find('center') or '')
    for tr in s.find_all('tr'):
        tds = tr.find_all('td', recursive=False)
        if len(tds) != 3: continue
        mid = txt(tds[1]); m = re.search(r'(\d+)\s*:\s*(\d+)', mid)
        if not m: continue
        a_side = [add_player(P, a) for a in tds[0].find_all('a', href=re.compile(r'ajaxPopup|/zawodnicy/')) if txt(a)]
        b_side = [add_player(P, a) for a in tds[2].find_all('a', href=re.compile(r'ajaxPopup|/zawodnicy/')) if txt(a)]
        a_side = list(dict.fromkeys(a_side)); b_side = list(dict.fromkeys(b_side))
        if not a_side and not b_side: continue
        label = mid[m.end():].strip()
        ms.append([tid, len(ms) + 1, '+'.join(a_side), '+'.join(b_side), m.group(1), m.group(2), game_of(label) or label,
                   'debel' if re.search(r'podw|debel', label, re.I) else '', date, ''])
    row = [tid, title[:200], date, date, 'league', '', 'archive', url, {'year': year}]
    store(row, ms, P); return len(ms)

# ---------------------------------------------------------------- main
def main():
    lst = tournament_list()
    say(f'pzbil.pl tournaments listed: {len(lst)}')
    n_new = n_upd = 0
    for t in lst:
        tid = f"T{t['id']}"
        if t['d1'] and t['d1'] > TODAY.isoformat(): continue
        old = TOUR.get(tid)
        empty = old and t['results'] and not any(m[0] == tid for m in D['matches'])
        if old and not ALL and not empty and old[6] == t['status'] and (t['d2'] or t['d1']) < CUTOFF and (old[8].get('results') == t['results']): continue
        try: row, ms, P = fetch_tournament(t)
        except Exception as e: say('  failed', tid, repr(e)[:120]); continue
        row[8]['results'] = t['results']
        store(row, ms, P)
        if old: n_upd += 1
        else: n_new += 1
        if (n_new + n_upd) % 100 == 0: save()       # a long first run keeps what it has read
    say(f'pzbil.pl tournaments: {n_new} new, {n_upd} re-read')
    save()
    for part in (league_new, archive):
        try: part()
        except Exception as e: say(f'  {part.__name__} stopped:', repr(e)[:150])
        save()
    kinds = {}
    for t in D['tournaments']: kinds[t[4]] = kinds.get(t[4], 0) + 1
    say(f'pzbil.pl stored: {kinds}, {len(D["matches"])} matches, {len(D["players"])} players')
    with open('update_log.txt', 'a', encoding='utf-8') as f: f.write('\n'.join(LOG) + '\n')

def save():
    if DEBUG:
        os.makedirs('data/pzbil_debug', exist_ok=True)
        for tid, h in DEBUG: open(f'data/pzbil_debug/{tid}.html', 'w', encoding='utf-8').write(h)
    D['tournaments'] = sorted(TOUR.values(), key=lambda t: (t[2] or '', t[0]))
    D['collected'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    os.makedirs(os.path.dirname(FILE) or '.', exist_ok=True)
    with gzip.open(FILE + '.tmp', 'wt', encoding='utf-8') as f: json.dump(D, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(FILE + '.tmp', FILE)

if __name__ == '__main__':
    main()
