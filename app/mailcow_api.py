import requests


class MailcowAPI:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    def _get(self, path: str):
        url = f'{self.base_url}/api/v1/{path}'
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict | None = None):
        url = f'{self.base_url}/api/v1/{path}'
        resp = self.session.post(url, json=data or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def test_connection(self) -> tuple[bool, str]:
        try:
            result = self._get('get/domain/all')
            if isinstance(result, list):
                return True, 'Connection OK'
            return False, str(result)
        except requests.RequestException as e:
            return False, str(e)

    def get_domains(self) -> list[dict]:
        return self._get('get/domain/all')

    def get_mailboxes(self, domain: str | None = None) -> list[dict]:
        if domain:
            return self._get(f'get/mailbox/{domain}')
        return self._get('get/mailbox/all')
