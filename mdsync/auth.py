import os
import sys
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive',
]


def find_config_file(filename: str) -> Optional[str]:
    """Find a config file in multiple possible locations."""
    search_paths = [
        Path.cwd() / filename,  # Current directory
        Path.home() / '.config' / 'mdsync' / filename,  # XDG config
        Path.home() / '.mdsync' / filename,  # Home directory
    ]
    
    for path in search_paths:
        if path.exists():
            return str(path)
    
    return None


def authenticate(force: bool = False):
    """Run the interactive Google OAuth flow and save fresh credentials."""
    credentials_file = find_config_file('credentials.json')
    if not credentials_file:
        print("Error: credentials.json not found!", file=sys.stderr)
        print("Searched in:", file=sys.stderr)
        print("  - Current directory", file=sys.stderr)
        print("  - ~/.config/mdsync/", file=sys.stderr)
        print("  - ~/.mdsync/", file=sys.stderr)
        print("\nPlease follow the setup instructions in SETUP_GUIDE.md", file=sys.stderr)
        raise FileNotFoundError('credentials.json not found')

    token_file = str(Path(credentials_file).parent / 'token.json')
    if force and os.path.exists(token_file):
        os.remove(token_file)

    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
    print("Opening a browser for Google authentication...", file=sys.stderr)
    print("If a browser does not open automatically, use the URL printed by Google below.", file=sys.stderr)
    creds = flow.run_local_server(port=0)
    with open(token_file, 'w') as token:
        token.write(creds.to_json())
    return creds


def get_credentials():
    """Get or create Google API credentials, re-authenticating when necessary."""
    creds = None
    
    # Find token file
    token_file = find_config_file('token.json')
    
    # The file token.json stores the user's access and refresh tokens
    if token_file and os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                # A revoked/expired refresh token cannot be repaired by refreshing;
                # discard it and transparently start OAuth again.
                if 'invalid_grant' not in str(exc):
                    raise
                print("Google authentication has expired or been revoked.", file=sys.stderr)
                creds = authenticate(force=True)
        else:
            creds = authenticate()
        
        # Save the credentials for the next run
        # Save in the same location as credentials, or current directory
        if not token_file:
            credentials_file = find_config_file('credentials.json')
            if credentials_file:
                token_file = str(Path(credentials_file).parent / 'token.json')
            else:
                token_file = 'token.json'
        
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    
    return creds
