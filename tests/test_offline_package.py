import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from scripts.package_offline import package


class OfflinePackageTests(unittest.TestCase):
    def image(self,directory,architecture,version='0.4.0'):
        path=Path(directory)/'image.tar'
        tag='koma:'+version+('-arm64' if architecture=='arm64' else '')
        entries={'manifest.json':[{'RepoTags':[tag],'Config':'config.json'}],
                 'config.json':{'architecture':architecture,'os':'linux','config':{'Labels':{'org.opencontainers.image.version':version}}}}
        with tarfile.open(path,'w') as archive:
            for name,value in entries.items():
                data=json.dumps(value).encode();member=tarfile.TarInfo(name);member.size=len(data)
                archive.addfile(member,io.BytesIO(data))
        return path

    def test_both_architectures_have_loadable_archive_templates_and_correct_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            for architecture in ['amd64','arm64']:
                image=self.image(directory,architecture)
                bundle,digest=package('v0.4.0',architecture,image,Path(__file__).resolve().parents[1],directory)
                with zipfile.ZipFile(bundle) as archive:
                    self.assertEqual(set(archive.namelist()),{f'koma-v0.4.0-linux-{architecture}.tar','compose.yaml','.env.example','README.txt'})
                    compose=archive.read('compose.yaml').decode()
                    self.assertIn('pull_policy: never',compose);self.assertNotIn('aweo/koma',compose)
                    self.assertIn('koma:0.4.0'+('-arm64' if architecture=='arm64' else ''),compose)
                    self.assertIn('docker load -i',archive.read('README.txt').decode())
                self.assertEqual(digest.read_text(),hashlib.sha256(bundle.read_bytes()).hexdigest()+'  '+bundle.name+'\n')

    def test_wrong_architecture_or_version_refuses_to_package(self):
        with tempfile.TemporaryDirectory() as directory:
            image=self.image(directory,'amd64')
            for tag,architecture in [('v0.4.0','arm64'),('v0.3.0','amd64')]:
                with self.assertRaises(ValueError):package(tag,architecture,image,directory,directory)


if __name__=='__main__':unittest.main()
