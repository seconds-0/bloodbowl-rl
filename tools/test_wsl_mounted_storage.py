import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools.wsl_mounted_storage import assess, collect, validate_mount


def fixture(mount='/mnt/d'):
    return {'target':mount, 'source':'D:\\', 'fstype':'9p', 'maj:min':'0:71',
            'options':'rw,noatime,aname=drvfs;path=D:\\;uid=1000;gid=1000,cache=0x5'}


class MountedStorageTests(unittest.TestCase):
    def test_exact_drvfs_mount(self):
        validate_mount(fixture(), '/mnt/d', 'D', '0:71')

    def test_guest_root_other_drive_subdirectory_or_changed_device_rejects(self):
        for key,value in [('target','/'), ('source','/dev/sdd'), ('source','C:\\'),
                          ('target','/mnt/d/subdir'), ('fstype','ext4'),
                          ('options','rw,aname=drvfs;path=C:\\;uid=1000'),
                          ('options','rw,aname=other;path=D:\\;uid=1000'),
                          ('maj:min','0:72')]:
            r=fixture();r[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                validate_mount(r,'/mnt/d','D','0:71')

    def test_exact_reserve_boundary(self):
        self.assertTrue(assess({'free_bytes':110},100,10)['accepted'])
        self.assertFalse(assess({'free_bytes':109},100,10)['accepted'])
        with self.assertRaises(ValueError):assess({'free_bytes':True},100)

    def test_real_query_contract_and_wrong_size(self):
        with tempfile.TemporaryDirectory() as directory:
            mount=os.path.realpath(directory);dev=os.stat(mount).st_dev
            r=fixture(mount);r['maj:min']=f'{os.major(dev)}:{os.minor(dev)}'
            result=SimpleNamespace(stdout=json.dumps({'filesystems':[r]}))
            usage=SimpleNamespace(f_blocks=1000,f_frsize=4096,f_bavail=500)
            with patch('tools.wsl_mounted_storage.subprocess.run',return_value=result) as run, patch('tools.wsl_mounted_storage.os.fstatvfs',return_value=usage):
                record=collect(mount,'D',4096000)
                self.assertEqual(record['free_bytes'],2048000)
                self.assertEqual(run.call_args.kwargs['timeout'],5)
                self.assertTrue(run.call_args.kwargs['check'])
                with self.assertRaises(ValueError):collect(mount,'D',4096001)

    def test_timeout_or_malformed_query_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            mount=os.path.realpath(directory)
            with patch('tools.wsl_mounted_storage.subprocess.run',side_effect=subprocess.TimeoutExpired('findmnt',5)):
                with self.assertRaises(subprocess.TimeoutExpired):collect(mount,'D',1)
            for text in ['garbage','{}','{"filesystems":[]}', '{"filesystems":[{},{}]}']:
                with patch('tools.wsl_mounted_storage.subprocess.run',return_value=SimpleNamespace(stdout=text)):
                    with self.assertRaises(ValueError):collect(mount,'D',1)


if __name__=='__main__':unittest.main()
