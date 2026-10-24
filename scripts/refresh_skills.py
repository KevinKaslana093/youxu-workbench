"""Collect public repository metadata and SKILL.md paths; never run repository code."""
import concurrent.futures, datetime, json, os, pathlib, subprocess, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / 'skill-catalog.json'
NOW = datetime.datetime.now(datetime.timezone.utc)
SINCE = (NOW - datetime.timedelta(days=30)).date().isoformat()

def get_api(endpoint):
    if os.environ.get('GITHUB_TOKEN'):
        req = urllib.request.Request('https://api.github.com/' + endpoint, headers={
            'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
            'Accept': 'application/vnd.github+json', 'User-Agent': 'Youxu-Skill-Discovery'})
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    result = subprocess.run(['gh', 'api', endpoint], capture_output=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError('GitHub query failed')
    return json.loads(result.stdout)

def inspect(repo):
    try:
        data = get_api('repos/' + repo['full_name'] + '/git/trees/' + urllib.parse.quote(repo['default_branch'], safe='') + '?recursive=1')
        return repo['full_name'], {'pathsChecked': True, 'checkedPaths': [t['path'] for t in data.get('tree', []) if t['type'] == 'blob' and (t['path'] == 'SKILL.md' or t['path'].endswith('/SKILL.md'))][:100], 'treeSha': data.get('sha'), 'treeTruncated': data.get('truncated', False), 'checkedAt': NOW.isoformat()}
    except Exception:
        return repo['full_name'], {'pathsChecked': False}

def main():
    previous = {}
    if DEST.exists():
        try: previous = json.loads(DEST.read_text(encoding='utf-8'))
        except Exception: pass
    queries, unique, failures = {}, {}, []
    for interest in ['codex', 'video', 'pptx', 'writing', 'workflow']:
        for mode in ['updated', 'new', 'stars']:
            label = interest + '|' + mode
            q = interest + ' skills in:name,description archived:false fork:false'
            if mode == 'updated': q += ' pushed:>=' + SINCE + ' stars:>=10'
            if mode == 'new': q += ' created:>=' + SINCE
            endpoint = 'search/repositories?' + urllib.parse.urlencode({'q': q, 'sort': 'stars' if mode == 'stars' else 'updated', 'order': 'desc', 'per_page': 6})
            try:
                result = get_api(endpoint)
                names = []
                for raw in result.get('items', []):
                    name = raw['full_name']
                    unique[name] = {k: raw.get(k) for k in ['full_name', 'name', 'description', 'default_branch', 'created_at', 'pushed_at', 'stargazers_count', 'license']}
                    names.append(name)
                queries[label] = {'names': names, 'queriedAt': NOW.isoformat(), 'partial': bool(result.get('incomplete_results'))}
            except Exception:
                failures.append(label)
            time.sleep(2.1)
    # Bound work per refresh. Unchecked candidates remain clearly marked in the UI.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for name, metadata in pool.map(inspect, list(unique.values())[:40]):
            unique[name].update(metadata)
    for label in failures:
        old = previous.get('queries', {}).get(label)
        if old:
            queries[label] = old
            for name in old['names']:
                if name not in unique and name in previous.get('repos', {}):
                    unique[name] = previous['repos'][name]
    if not queries: raise RuntimeError('No current or previous catalog available')
    payload = {'version': 1, 'generatedAt': NOW.isoformat(), 'refreshHours': 6, 'queries': queries, 'repos': unique, 'failedQueries': failures}
    DEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'queries': len(queries), 'repos': len(unique), 'failedQueries': failures}))

if __name__ == '__main__': main()
