"""Append-only Drive photo album. Existing page bytes and placements are immutable."""
import copy
import hashlib
import json
import re
from pathlib import Path

import gdown
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageOps
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def list_photos(folder_id, session=None, seen=None):
    """Public embedded folder view avoids the old 50-item folder-page limit."""
    session = session or requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
    seen = seen if seen is not None else set()
    if folder_id in seen:
        return []
    seen.add(folder_id)
    response = session.get('https://drive.google.com/embeddedfolderview', params={'id': folder_id}, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    if not soup.select('.flip-entries'):
        raise RuntimeError('Drive folder listing unavailable; refusing to publish an incomplete album.')
    photos = {}
    for entry in soup.select('.flip-entry'):
        anchor = entry.select_one('a[href]')
        if not anchor:
            continue
        href = anchor['href']
        title = entry.select_one('.flip-entry-title')
        name = title.get_text(strip=True) if title else anchor.get_text(strip=True)
        file_match = re.search(r'drive\.google\.com/file/d/([\w-]+)/', href)
        folder_match = re.search(r'drive\.google\.com/drive/folders/([\w-]+)', href)
        if file_match and Path(name).suffix.lower() in EXTENSIONS:
            file_id = file_match.group(1)
            photos[file_id] = {'id': file_id, 'name': name}
        elif folder_match:
            for photo in list_photos(folder_match.group(1), session, seen):
                photos[photo['id']] = photo
    return sorted(photos.values(), key=lambda p: (p['name'], p['id']))


def boxes_for(ratios, width, height):
    margin, gap = round(width * .065), round(width * .028)
    x, y = margin, round(height * .08)
    w, h = width - margin * 2, round(height * .84)
    n = len(ratios)
    if n == 1:
        return 'single', [[x, y, w, h]]
    if n == 2 and all(r < .95 for r in ratios):
        half = (w - gap) // 2
        return 'pair-columns', [[x, y, half, h], [x + half + gap, y, half, h]]
    # Rows preserve landscape photographs without cropping; mixed pages use
    # one large landscape row and a pair of portraits when applicable.
    if n == 3 and ratios[0] > 1.1 and ratios[1] < 1 and ratios[2] < 1:
        top = round(h * .44)
        half = (w - gap) // 2
        return 'hero-pair', [[x, y, w, top], [x, y + top + gap, half, h-top-gap], [x+half+gap, y+top+gap, half, h-top-gap]]
    row = (h - gap * (n - 1)) // n
    return f'{n}-rows', [[x, y + i * (row + gap), w, row] for i in range(n)]


def append_pages(state, photos, config):
    result = copy.deepcopy(state)
    known = {p['id'] for page in result['pages'] for p in page['photos']}
    pending = sorted((p for p in photos if p['id'] not in known), key=lambda p: (p['name'], p['id']))
    while pending:
        # Portraits benefit from larger slots. Landscape sequences fit three rows.
        count = 3 if len(pending) >= 3 and all(p['width']/p['height'] > 1.1 for p in pending[:3]) else 2
        if pending[0]['width']/pending[0]['height'] < .8:
            count = 1
        group, pending = pending[:count], pending[count:]
        number = len(result['pages']) + 1
        if number > config['maxPages']:
            raise RuntimeError('Unity page URL capacity exceeded; increase Unity capacity and maxPages together.')
        template, boxes = boxes_for([p['width']/p['height'] for p in group], config['width'], config['height'])
        result['pages'].append({'number': number, 'file': f'pages/page_{number:04d}.jpg',
            'width': config['width'], 'height': config['height'], 'background': config['background'],
            'template': template, 'photos': [dict(p, box=box) for p, box in zip(group, boxes)]})
    return result


def render(page, cache, target):
    canvas = Image.new('RGB', (page['width'], page['height']), page['background'])
    draw = ImageDraw.Draw(canvas)
    for photo in page['photos']:
        x, y, w, h = photo['box']
        with Image.open(cache / photo['id']) as original:
            picture = ImageOps.exif_transpose(original).convert('RGB')
            picture = ImageOps.contain(picture, (w - 24, h - 24), Image.Resampling.LANCZOS)
        px, py = x + (w-picture.width)//2, y + (h-picture.height)//2
        draw.rectangle((px-12, py-12, px+picture.width+11, py+picture.height+11), fill='white')
        canvas.paste(picture, (px, py))
    draw.text((page['width']//2, page['height']-60), str(page['number']), fill='#887b68', anchor='mm', font_size=24)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, 'JPEG', quality=90, optimize=True, subsampling=0)


def validate(state, output):
    ids = set()
    for number, page in enumerate(state['pages'], 1):
        assert page['number'] == number and page['file'] == f'pages/page_{number:04d}.jpg'
        assert 1 <= len(page['photos']) <= 3
        for photo in page['photos']:
            assert photo['id'] not in ids
            ids.add(photo['id'])
            x, y, w, h = photo['box']
            assert min(x, y) >= 0 and min(w, h) > 0
            assert x+w <= page['width'] and y+h <= page['height']
        target = output / page['file']
        assert hashlib.sha256(target.read_bytes()).hexdigest() == page['sha256'], f'Frozen page changed: {target}'
        with Image.open(target) as image:
            assert image.size == (page['width'], page['height'])
            assert image.format == 'JPEG' and max(image.size) <= 2048
            image.verify()


def build():
    config = json.loads((ROOT/'album_config.json').read_text(encoding='utf-8'))
    state = json.loads((ROOT/'album_state.json').read_text(encoding='utf-8'))
    output, cache = ROOT/'public', ROOT/'.cache'
    cache.mkdir(exist_ok=True)
    validate(state, output)
    listing = list_photos(config['folderId'])
    if not listing:
        raise RuntimeError('No supported photos found; keeping the last published album.')
    known = {p['id'] for page in state['pages'] for p in page['photos']}
    new = []
    for photo in listing:
        if photo['id'] in known:
            continue
        destination = cache/photo['id']
        if not gdown.download(id=photo['id'], output=str(destination), quiet=True, use_cookies=False):
            raise RuntimeError(f"Download failed: {photo['id']}")
        with Image.open(destination) as image:
            image = ImageOps.exif_transpose(image)
            image.load()
            new.append(dict(photo, width=image.width, height=image.height))
    updated = append_pages(state, new, config)
    for page in updated['pages'][len(state['pages']):]:
        target = output/page['file']
        render(page, cache, target)
        page['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    validate(updated, output)
    manifest = {'schemaVersion': 1, 'pageCount': len(updated['pages']),
        'photoCount': sum(len(p['photos']) for p in updated['pages']),
        'pages': [{'number': p['number'], 'url': config['baseUrl']+'/'+p['file'], 'sha256': p['sha256']} for p in updated['pages']]}
    output.mkdir(exist_ok=True)
    write_json(output/'album.json', manifest)
    write_json(ROOT/'album_state.json', updated)
    print(f"Drive: {len(listing)} photos; added: {len(new)}; published: {manifest['pageCount']} pages")


if __name__ == '__main__':
    build()
