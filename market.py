"""Public DSH market catalog. Remote install strings are never executed."""
import json
import math
import re
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit

CATALOG_URL = 'https://awesome-dsh-plugin.com/plugins.json'
PACKAGE = re.compile(r'^(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*$')
VERSION = re.compile(r'^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$')


def normalize_stars(value):
    # The catalog publishes numbers or null, not formatted numeric strings.
    # Do not turn missing or malformed observations into a measured zero.
    if type(value) not in (int, float) or not 0 <= value <= 2**53-1:
        return None
    if not math.isfinite(value) or int(value) != value:
        return None
    return int(value)


def safe_url(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        return ''
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname:
            return ''
        return urlunsplit(('https', url.hostname, url.path, '', ''))
    except ValueError:
        return ''


def normalize_catalog(data):
    if not isinstance(data, dict) or not isinstance(data.get('plugins'), list):
        raise RuntimeError('插件市场返回的数据格式不受支持。')
    categories = {key: value.get('zh') or value.get('en') or key
                  for key, value in data.get('categories', {}).items() if isinstance(value, dict)}
    # This dates the catalog snapshot, not a separate live GitHub observation.
    stars_as_of = data.get('updated') if isinstance(data.get('updated'), str) else None
    items = []
    for raw in data['plugins']:
        if not isinstance(raw, dict) or not isinstance(raw.get('name'), str):
            continue
        description = raw.get('description', {})
        description = description.get('zh') or description.get('en', '') if isinstance(description, dict) else str(description)
        category = raw.get('category', [])
        category = [category] if isinstance(category, str) else category if isinstance(category, list) else []
        npm, version = str(raw.get('npm') or ''), str(raw.get('version') or '')
        items.append({'name': raw['name'], 'owner': str(raw.get('owner') or ''),
                      'url': safe_url(raw.get('url')), 'npm': npm, 'version': version,
                      'description': description[:2500], 'categories': category,
                      'stars': normalize_stars(raw.get('stars')),
                      'stars_source': CATALOG_URL, 'stars_as_of': stars_as_of,
                      'installable': bool(PACKAGE.fullmatch(npm) and VERSION.fullmatch(version))})
    return {'items': items, 'categories': categories, 'updated': str(data.get('updated', '')), 'source': CATALOG_URL}


def fetch_catalog():
    req = Request(CATALOG_URL, headers={'User-Agent': 'DSH-Plugin-Host/0.1', 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=25) as response:
            payload = response.read(20 * 1024 * 1024 + 1)
        if len(payload) > 20 * 1024 * 1024:
            raise RuntimeError('插件市场目录过大，未加载。')
        return normalize_catalog(json.loads(payload))
    except (OSError, ValueError) as exc:
        raise RuntimeError('暂时无法读取插件市场，请检查网络后重试。') from exc
