"""Fetch the pinned native test dependency from the upstream release."""
import hashlib
from pathlib import Path
import platform
import sys
import tempfile
import urllib.request
import zipfile

assets = {
    ('darwin', 'arm64'): ('Darwin_arm', '0fc7354dff9e98c255eea64e1e6f55add0a9c39ec8f79fe26aec61032cbfa908'),
    ('darwin', 'x86_64'): ('Darwin_i386', 'a2c53d03e9b8c4d226f2330c30334b613c198448a66b42f3fae6afe159fe8f8e'),
    ('linux', 'x86_64'): ('Linux_x86_64', '012787f95bca91d00aa5baaad87ace528fa9d39a478d3377107812cf376f1b11'),
}
asset, expected = assets[(sys.platform, platform.machine().lower())]
with tempfile.TemporaryDirectory() as temp:
    archive = Path(temp) / 'todds.zip'
    urllib.request.urlretrieve(f'https://github.com/todds-encoder/todds/releases/download/0.4.1/todds_{asset}_0.4.1.zip', archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Native encoder checksum mismatch')
    target = Path(__file__).resolve().parents[1] / 'todds/todds'
    with zipfile.ZipFile(archive) as payload:
        # Extract only the encoder, retaining the source tree's license and docs.
        target.write_bytes(payload.read('todds'))
    target.chmod(0o755)
