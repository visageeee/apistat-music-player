"""Generate application credentials for distribution builds.

These credentials can be extracted from distributed apps and must not be
personal account credentials. Never print their values or commit this file.
"""
import os
import sys
from pathlib import Path


def main():
    target = Path(__file__).resolve().parent.parent / 'lastfm_build_credentials.py'
    key = os.environ.get('LASTFM_API_KEY', '').strip()
    secret = os.environ.get('LASTFM_API_SECRET', '').strip()
    if not key and not secret:
        target.unlink(missing_ok=True)
        if '--require' in sys.argv[1:]:
            raise SystemExit('Set the LASTFM_API_KEY and LASTFM_API_SECRET build secrets before building.')
        print('No Last.fm application credentials configured for this build.')
        return
    if not key or not secret:
        raise SystemExit('Both LASTFM_API_KEY and LASTFM_API_SECRET are required.')
    target.write_text('# Generated during the build; do not commit.\n'
                      f'API_KEY = {key!r}\nAPI_SECRET = {secret!r}\n', encoding='utf-8')
    print('Last.fm application credentials configured for this build.')


if __name__ == '__main__':
    main()
