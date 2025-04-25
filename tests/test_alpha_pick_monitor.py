import sys, os
import types
sys.modules['streamlit'] = types.ModuleType('streamlit')
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
import alpha_pick_monitor

def test_fetch_email_picks(monkeypatch):
    # Set test credentials
    monkeypatch.setattr(alpha_pick_monitor, 'EMAIL_HOST', 'host')
    monkeypatch.setattr(alpha_pick_monitor, 'EMAIL_USER', 'user')
    monkeypatch.setattr(alpha_pick_monitor, 'EMAIL_PASS', 'pass')

    # Dummy IMAP class to simulate Gmail interactions
    class DummyIMAP:
        def __init__(self, host):
            assert host == 'host'
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def login(self, user, password):
            assert user == 'user'
            assert password == 'pass'
        def select(self, mailbox):
            assert mailbox == 'INBOX'
        def search(self, charset, criteria):
            assert charset is None
            assert f'FROM "{alpha_pick_monitor.ALPHA_EMAIL_SENDER}"' in criteria
            return 'OK', [b'1']
        def fetch(self, uid, fmt):
            assert uid == b'1'
            assert fmt == '(RFC822)'
            # Construct a minimal email bytes with subject and date
            msg_bytes = (b"Subject: Alpha Pick AAPL\r\n"
                         b"Date: Mon, 1 Jan 2021 12:00:00 +0000\r\n"
                         b"\r\n"
                         b"Body")
            return 'OK', [(None, msg_bytes)]

    # Patch IMAP4_SSL to our dummy class
    monkeypatch.setattr(alpha_pick_monitor.imaplib, 'IMAP4_SSL', DummyIMAP)

    # Execute and verify
    rows = alpha_pick_monitor.fetch_email_picks()
    assert rows == [('AAPL', '2021-01-01')]


def test_fetch_email_picks_no_credentials(monkeypatch):
    # Clear credentials to simulate missing env vars
    monkeypatch.setattr(alpha_pick_monitor, 'EMAIL_HOST', None)
    monkeypatch.setattr(alpha_pick_monitor, 'EMAIL_USER', None)
    monkeypatch.setattr(alpha_pick_monitor, 'EMAIL_PASS', None)

    rows = alpha_pick_monitor.fetch_email_picks()
    assert rows == [] 