"""Offline, service-account-only Vertex configuration. Never discovers credentials."""
import json
import re

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

MAX_SERVICE_ACCOUNT_BYTES = 32768


def vertex_endpoint(project: str, location: str) -> str:
    if (not isinstance(project, str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', project)
            or not isinstance(location, str) or len(location) > 63 or not re.fullmatch(r'global|[a-z]+(?:-[a-z]+)+[1-9][0-9]*', location)):
        raise ValueError('invalid_vertex_configuration')
    host = 'aiplatform.googleapis.com' if location == 'global' else location + '-aiplatform.googleapis.com'
    return f'https://{host}/v1/projects/{project}/locations/{location}/publishers/google'


def vertex_metadata(row):
    """Conditional fields preserve historical non-Vertex dictionaries and hashes."""
    if row.get('provider') != 'vertex_ai' and row.get('protocol') != 'vertex_ai':
        return {}
    project, location = row.get('vertex_project'), row.get('vertex_location')
    vertex_endpoint(project, location)
    if row.get('provider', 'vertex_ai') != 'vertex_ai' or row.get('protocol') != 'vertex_ai':
        raise ValueError('invalid_vertex_configuration')
    return {'vertex_project': project, 'vertex_location': location}


def parse_service_account(secret: str) -> dict:
    try:
        if not isinstance(secret, str) or not 1 <= len(secret.encode('utf-8')) <= MAX_SERVICE_ACCOUNT_BYTES:
            raise ValueError()
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        value = json.loads(secret, object_pairs_hook=unique)
        required = {'type', 'project_id', 'private_key_id', 'private_key', 'client_email', 'client_id', 'token_uri'}
        optional = {'auth_uri', 'auth_provider_x509_cert_url', 'client_x509_cert_url', 'universe_domain'}
        if (not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional
                or any(not isinstance(v, str) or not v for v in value.values())
                or value['type'] != 'service_account'
                or value['token_uri'] != 'https://oauth2.googleapis.com/token'
                or value.get('universe_domain', 'googleapis.com') != 'googleapis.com'):
            raise ValueError()
        vertex_endpoint(value['project_id'], 'global')
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['private_key_id'])
                or not re.fullmatch(r'[0-9]{1,64}', value['client_id'])
                or not re.fullmatch(r'[a-zA-Z0-9._-]+@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com', value['client_email'])):
            raise ValueError()
        fixed = {'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                 'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs'}
        if any(k in value and value[k] != v for k, v in fixed.items()):
            raise ValueError()
        if 'client_x509_cert_url' in value and value['client_x509_cert_url'] not in {
            'https://www.googleapis.com/robot/v1/metadata/x509/' + value['client_email'],
            'https://www.googleapis.com/robot/v1/metadata/x509/' + value['client_email'].replace('@', '%40')}:
            raise ValueError()
        key = load_pem_private_key(value['private_key'].encode('ascii'), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, UnsupportedAlgorithm):
        raise ValueError('invalid_service_account') from None
