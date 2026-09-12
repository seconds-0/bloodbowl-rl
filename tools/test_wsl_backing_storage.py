import unittest
from tools.check_wsl_backing_storage import assess


class BackingStorageTests(unittest.TestCase):
    def test_full_host_rejects_despite_large_guest_capacity(self):
        record = {'free_bytes':7467008, 'volume_bytes':999545966592,
                  'vhd_file_bytes':271207890944, 'guest_free_bytes':724*(1<<30)}
        self.assertFalse(assess(record, 100*(1<<30), 8279438892)['accepted'])

    def test_destination_must_cover_copy_and_reserve(self):
        record = {'free_bytes':1610867363840, 'volume_bytes':2000381014016,
                  'vhd_file_bytes':271207890944}
        self.assertTrue(assess(record, 100*(1<<30), record['vhd_file_bytes'])['accepted'])
        record['free_bytes'] = record['vhd_file_bytes'] + 100*(1<<30) - 1
        self.assertFalse(assess(record, 100*(1<<30), record['vhd_file_bytes'])['accepted'])

    def test_missing_malformed_or_impossible_measurement_rejects(self):
        for record in [{}, {'free_bytes':True, 'volume_bytes':100, 'vhd_file_bytes':1},
                       {'free_bytes':101, 'volume_bytes':100, 'vhd_file_bytes':1}]:
            with self.assertRaises(ValueError): assess(record, 1)


if __name__ == '__main__': unittest.main()
