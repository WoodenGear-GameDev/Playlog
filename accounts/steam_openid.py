import re
from urllib.parse import urlencode

import requests

STEAM_OPENID_URL = 'https://steamcommunity.com/openid/login'
CLAIMED_ID_RE = re.compile(r'^https?://steamcommunity\.com/openid/id/(\d{17})$')


def build_login_url(return_to, realm):
    params = {
        'openid.ns': 'http://specs.openid.net/auth/2.0',
        'openid.mode': 'checkid_setup',
        'openid.return_to': return_to,
        'openid.realm': realm,
        'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select',
        'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select',
    }
    return f'{STEAM_OPENID_URL}?{urlencode(params)}'


def verify_assertion(params, expected_return_to):
    """Проверяет ответ Steam. Возвращает SteamID64 (строку) или None."""
    if params.get('openid.mode') != 'id_res':
        return None
    if params.get('openid.op_endpoint') != STEAM_OPENID_URL:
        return None
    if params.get('openid.return_to') != expected_return_to:
        return None

    claimed_id = params.get('openid.claimed_id', '')
    match = CLAIMED_ID_RE.match(claimed_id)
    if not match or params.get('openid.identity') != claimed_id:
        return None

    # Главная проверка: только сам Steam может подтвердить, что подпись настоящая
    data = {k: v for k, v in params.items() if k.startswith('openid.')}
    data['openid.mode'] = 'check_authentication'
    try:
        response = requests.post(STEAM_OPENID_URL, data=data, timeout=10)
    except requests.RequestException:
        return None
    if response.status_code != 200 or 'is_valid:true' not in response.text:
        return None

    return match.group(1)