"""run_tests.py
Simple end-to-end test: register a test user, call verify, then fetch profiles.
Uses only Python stdlib so no extra deps required.
"""
import json
import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:5000'

def post(path, payload):
    url = BASE + path
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode(), json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {'error': str(e)}
    except Exception as e:
        return None, {'error': str(e)}

def get(path):
    url = BASE + path
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.getcode(), json.loads(resp.read().decode())
    except Exception as e:
        return None, {'error': str(e)}

def main():
    username = f'test_user_{int(__import__("time").time())}'
    print('Registering user:', username)
    payload = {
        'username': username,
        'flight': [120, 130, 110],
        'dwell': [80, 90, 85],
        'mouse_speed': 5.5,
        'scrolls': 2
    }
    code, res = post('/register', payload)
    print('POST /register', code, res)

    print('Calling verify for user (simulate session)...')
    payload2 = {
        'username': username,
        'flight': [125, 128, 115],
        'dwell': [82, 92, 88],
        'mouse_speed': 5.8,
        'scrolls': 2,
        'clicks': 3,
        'fraud_score': 5
    }
    code, res = post('/verify', payload2)
    print('POST /verify', code, res)

    print('\nFetching /profiles')
    code, res = get('/profiles')
    print('GET /profiles', code)
    if isinstance(res, dict):
        # print only the test user entry and default_user for brevity
        for k in sorted(res.keys()):
            if k in (username, 'default_user'):
                print(k, json.dumps(res[k], indent=2))
    else:
        print(res)

if __name__ == '__main__':
    main()
