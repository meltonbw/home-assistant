"""The tests for Home Assistant frontend."""
import asyncio
import re
from unittest.mock import patch

import pytest

from homeassistant.setup import async_setup_component
from homeassistant.components.frontend import DOMAIN, ATTR_THEMES


@pytest.fixture
def mock_http_client(hass, test_client):
    """Start the Hass HTTP component."""
    hass.loop.run_until_complete(async_setup_component(hass, 'frontend', {}))
    return hass.loop.run_until_complete(test_client(hass.http.app))


@pytest.fixture
def mock_http_client_with_themes(hass, test_client):
    """Start the Hass HTTP component."""
    hass.loop.run_until_complete(async_setup_component(hass, 'frontend', {
        DOMAIN: {
            ATTR_THEMES: {
                'happy': {
                    'primary-color': 'red'
                }
            }
        }}))
    return hass.loop.run_until_complete(test_client(hass.http.app))


@asyncio.coroutine
def test_frontend_and_static(mock_http_client):
    """Test if we can get the frontend."""
    resp = yield from mock_http_client.get('')
    assert resp.status == 200
    assert 'cache-control' not in resp.headers

    text = yield from resp.text()

    # Test we can retrieve frontend.js
    frontendjs = re.search(
        r'(?P<app>\/static\/frontend-[A-Za-z0-9]{32}.html)', text)

    assert frontendjs is not None
    resp = yield from mock_http_client.get(frontendjs.groups(0)[0])
    assert resp.status == 200
    assert 'public' in resp.headers.get('cache-control')


@asyncio.coroutine
def test_dont_cache_service_worker(mock_http_client):
    """Test that we don't cache the service worker."""
    resp = yield from mock_http_client.get('/service_worker.js')
    assert resp.status == 200
    assert 'cache-control' not in resp.headers


@asyncio.coroutine
def test_404(mock_http_client):
    """Test for HTTP 404 error."""
    resp = yield from mock_http_client.get('/not-existing')
    assert resp.status == 404


@asyncio.coroutine
def test_we_cannot_POST_to_root(mock_http_client):
    """Test that POST is not allow to root."""
    resp = yield from mock_http_client.post('/')
    assert resp.status == 405


@asyncio.coroutine
def test_states_routes(mock_http_client):
    """All served by index."""
    resp = yield from mock_http_client.get('/states')
    assert resp.status == 200

    resp = yield from mock_http_client.get('/states/group.existing')
    assert resp.status == 200


@asyncio.coroutine
def test_themes_api(mock_http_client_with_themes):
    """Test that /api/themes returns correct data."""
    resp = yield from mock_http_client_with_themes.get('/api/themes')
    json = yield from resp.json()
    assert json['default_theme'] == 'default'
    assert json['themes'] == {'happy': {'primary-color': 'red'}}


@asyncio.coroutine
def test_themes_set_theme(hass, mock_http_client_with_themes):
    """Test frontend.set_theme service."""
    yield from hass.services.async_call(DOMAIN, 'set_theme', {'name': 'happy'})
    yield from hass.async_block_till_done()
    resp = yield from mock_http_client_with_themes.get('/api/themes')
    json = yield from resp.json()
    assert json['default_theme'] == 'happy'

    yield from hass.services.async_call(
        DOMAIN, 'set_theme', {'name': 'default'})
    yield from hass.async_block_till_done()
    resp = yield from mock_http_client_with_themes.get('/api/themes')
    json = yield from resp.json()
    assert json['default_theme'] == 'default'


@asyncio.coroutine
def test_themes_set_theme_wrong_name(hass, mock_http_client_with_themes):
    """Test frontend.set_theme service called with wrong name."""
    yield from hass.services.async_call(DOMAIN, 'set_theme', {'name': 'wrong'})
    yield from hass.async_block_till_done()
    resp = yield from mock_http_client_with_themes.get('/api/themes')
    json = yield from resp.json()
    assert json['default_theme'] == 'default'


@asyncio.coroutine
def test_themes_reload_themes(hass, mock_http_client_with_themes):
    """Test frontend.reload_themes service."""
    with patch('homeassistant.components.frontend.load_yaml_config_file',
               return_value={DOMAIN: {
                   ATTR_THEMES: {
                       'sad': {'primary-color': 'blue'}
                   }}}):
        yield from hass.services.async_call(DOMAIN, 'set_theme',
                                            {'name': 'happy'})
        yield from hass.services.async_call(DOMAIN, 'reload_themes')
        yield from hass.async_block_till_done()
        resp = yield from mock_http_client_with_themes.get('/api/themes')
        json = yield from resp.json()
        assert json['themes'] == {'sad': {'primary-color': 'blue'}}
        assert json['default_theme'] == 'default'


@asyncio.coroutine
def test_missing_themes(mock_http_client):
    """Test that themes API works when themes are not defined."""
    resp = yield from mock_http_client.get('/api/themes')
    assert resp.status == 200
    json = yield from resp.json()
    assert json['default_theme'] == 'default'
    assert json['themes'] == {}
