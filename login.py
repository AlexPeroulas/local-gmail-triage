import sys
from gmail_client import get_service, login, get_address, token_path, NotSignedIn
from store import load_config


def sign_in(label, expected, force=False):
    # returns a Gmail service, or None if the wrong Google account was used
    svc = None
    if not force:
        try:
            svc = get_service(label)
        except NotSignedIn:
            pass
    if svc is None:
        print(f"{label:<10} {expected:<32} opening browser...")
        svc = login(label, expected)

    actual = get_address(svc)
    if actual.lower() != expected.lower():
        token_path(label).unlink()
        print(f"{label:<10} {expected:<32} wrong account: signed in as {actual}. Run: python login.py {label}")
        return None
    print(f"{label:<10} {expected:<32} signed in")
    return svc


def main(labels):
    accounts = load_config()["accounts"]
    force = bool(labels)   # naming an account always signs in again
    ok = True

    for label in labels or accounts:
        if label not in accounts:
            print(f"{label:<10} unknown account (not in config.json)")
            ok = False
        elif sign_in(label, accounts[label], force) is None:
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
