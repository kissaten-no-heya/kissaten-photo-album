import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from build_album import append_pages, get_folder_id, list_photos, migrate_state, photo_key, render

CONFIG = {'width': 1448, 'height': 2048, 'maxPages': 100, 'background': '#f5f0e6'}


def photos(n, width=1600, height=900):
    return [{'id': str(i), 'name': f'{i:04d}.png', 'width': width, 'height': height} for i in range(n)]


class AlbumTests(unittest.TestCase):
    def test_private_state_migration_is_stable_and_preserves_layout(self):
        legacy = append_pages({'schemaVersion': 1, 'pages': []}, photos(4), CONFIG)
        legacy['pages'][0]['photos'][0]['name'] = 'private-original.png'
        snapshot = copy.deepcopy(legacy)
        migrated = migrate_state(legacy)
        self.assertEqual(legacy, snapshot)
        self.assertEqual(migrated['schemaVersion'], 2)
        self.assertNotIn('private-original.png', json.dumps(migrated))
        for old, new in zip(legacy['pages'], migrated['pages']):
            self.assertEqual(old['file'], new['file'])
            self.assertEqual(old['template'], new['template'])
            for before, after in zip(old['photos'], new['photos']):
                self.assertEqual(after['id'], photo_key(before['id']))
                self.assertEqual(after['box'], before['box'])
        incoming = [dict(p, id=photo_key(p['id'])) for p in photos(4)]
        self.assertEqual(append_pages(migrated, incoming, CONFIG), migrated)
        self.assertEqual(migrate_state(migrated), migrated)

    def test_folder_id_requires_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                get_folder_id()
        with patch.dict(os.environ, {'DRIVE_FOLDER_ID': 'example_folder_id'}):
            self.assertEqual(get_folder_id(), 'example_folder_id')

    def test_append_preserves_partial_page_and_renames(self):
        original = append_pages({'pages': []}, photos(4), CONFIG)
        snapshot = copy.deepcopy(original)
        incoming = photos(8)
        incoming[0]['name'] = 'renamed.png'
        updated = append_pages(original, incoming, CONFIG)
        self.assertEqual(original, snapshot)
        self.assertEqual(updated['pages'][:2], snapshot['pages'])
        self.assertEqual(sum(len(p['photos']) for p in updated['pages']), 8)
        self.assertEqual(append_pages(updated, incoming, CONFIG), updated)
        self.assertEqual(append_pages(updated, [], CONFIG), updated)

    def test_all_counts_and_capacity(self):
        for count in range(1, 15):
            state = append_pages({'pages': []}, photos(count), CONFIG)
            self.assertEqual(sum(len(p['photos']) for p in state['pages']), count)
            self.assertTrue(all(1 <= len(p['photos']) <= 3 for p in state['pages']))
        with self.assertRaises(RuntimeError):
            append_pages({'pages': []}, photos(4), dict(CONFIG, maxPages=1))

    def test_portrait_and_render(self):
        for source in (photos(1, 900, 1600), photos(2, 1100, 1200), photos(3)):
            state = append_pages({'pages': []}, source, CONFIG)
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for photo in source:
                    Image.new('RGB', (photo['width'], photo['height']), '#468abc').save(root/photo['id'], 'PNG')
                render(state['pages'][0], root, root/'result.jpg')
                with Image.open(root/'result.jpg') as result:
                    self.assertEqual(result.size, (1448, 2048))

    def test_listing_over_50_and_invalid_response(self):
        entries = ''.join(f'<div class="flip-entry"><a href="https://drive.google.com/file/d/id{i}/view"><div class="flip-entry-title">{i}.png</div></a></div>' for i in range(75))
        session = Mock()
        session.get.return_value.text = '<div class="flip-entries">'+entries+'</div>'
        self.assertEqual(len(list_photos('folder', session)), 75)
        session.get.return_value.text = '<html>Sign in</html>'
        with self.assertRaises(RuntimeError):
            list_photos('folder', session)


if __name__ == '__main__':
    unittest.main()
