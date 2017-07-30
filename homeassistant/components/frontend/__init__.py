"""Handle the frontend for Home Assistant."""
import asyncio
import hashlib
import json
import logging
import os

from aiohttp import web
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.config import find_config_file, load_yaml_config_file
from homeassistant.const import CONF_NAME, EVENT_THEMES_UPDATED
from homeassistant.core import callback
from homeassistant.loader import bind_hass
from homeassistant.components import api
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import is_trusted_ip
from homeassistant.components.http.const import KEY_DEVELOPMENT
from .version import FINGERPRINTS

DOMAIN = 'frontend'
DEPENDENCIES = ['api', 'websocket_api']

URL_PANEL_COMPONENT = '/frontend/panels/{}.html'
URL_PANEL_COMPONENT_FP = '/frontend/panels/{}-{}.html'

STATIC_PATH = os.path.join(os.path.dirname(__file__), 'www_static/')

ATTR_THEMES = 'themes'
DEFAULT_THEME_COLOR = '#03A9F4'
MANIFEST_JSON = {
    'background_color': '#FFFFFF',
    'description': 'Open-source home automation platform running on Python 3.',
    'dir': 'ltr',
    'display': 'standalone',
    'icons': [],
    'lang': 'en-US',
    'name': 'Home Assistant',
    'short_name': 'Assistant',
    'start_url': '/',
    'theme_color': DEFAULT_THEME_COLOR
}

for size in (192, 384, 512, 1024):
    MANIFEST_JSON['icons'].append({
        'src': '/static/icons/favicon-{}x{}.png'.format(size, size),
        'sizes': '{}x{}'.format(size, size),
        'type': 'image/png'
    })

DATA_PANELS = 'frontend_panels'
DATA_INDEX_VIEW = 'frontend_index_view'
DATA_THEMES = 'frontend_themes'
DATA_DEFAULT_THEME = 'frontend_default_theme'
DEFAULT_THEME = 'default'

PRIMARY_COLOR = 'primary-color'

# To keep track we don't register a component twice (gives a warning)
_REGISTERED_COMPONENTS = set()
_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(ATTR_THEMES): vol.Schema({
            cv.string: {cv.string: cv.string}
        }),
    }),
}, extra=vol.ALLOW_EXTRA)

SERVICE_SET_THEME = 'set_theme'
SERVICE_RELOAD_THEMES = 'reload_themes'
SERVICE_SET_THEME_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
})


@bind_hass
def register_built_in_panel(hass, component_name, sidebar_title=None,
                            sidebar_icon=None, url_path=None, config=None):
    """Register a built-in panel."""
    nondev_path = 'panels/ha-panel-{}.html'.format(component_name)

    if hass.http.development:
        url = ('/static/home-assistant-polymer/panels/'
               '{0}/ha-panel-{0}.html'.format(component_name))
        path = os.path.join(
            STATIC_PATH, 'home-assistant-polymer/panels/',
            '{0}/ha-panel-{0}.html'.format(component_name))
    else:
        url = None  # use default url generate mechanism
        path = os.path.join(STATIC_PATH, nondev_path)

    # Fingerprint doesn't exist when adding new built-in panel
    register_panel(hass, component_name, path,
                   FINGERPRINTS.get(nondev_path, 'dev'), sidebar_title,
                   sidebar_icon, url_path, url, config)


@bind_hass
def register_panel(hass, component_name, path, md5=None, sidebar_title=None,
                   sidebar_icon=None, url_path=None, url=None, config=None):
    """Register a panel for the frontend.

    component_name: name of the web component
    path: path to the HTML of the web component
    md5: the md5 hash of the web component (for versioning, optional)
    sidebar_title: title to show in the sidebar (optional)
    sidebar_icon: icon to show next to title in sidebar (optional)
    url_path: name to use in the url (defaults to component_name)
    url: for the web component (for dev environment, optional)
    config: config to be passed into the web component

    Warning: this API will probably change. Use at own risk.
    """
    panels = hass.data.get(DATA_PANELS)
    if panels is None:
        panels = hass.data[DATA_PANELS] = {}

    if url_path is None:
        url_path = component_name

    if url_path in panels:
        _LOGGER.warning("Overwriting component %s", url_path)
    if not os.path.isfile(path):
        _LOGGER.error(
            "Panel %s component does not exist: %s", component_name, path)
        return

    if md5 is None:
        with open(path) as fil:
            md5 = hashlib.md5(fil.read().encode('utf-8')).hexdigest()

    data = {
        'url_path': url_path,
        'component_name': component_name,
    }

    if sidebar_title:
        data['title'] = sidebar_title
    if sidebar_icon:
        data['icon'] = sidebar_icon
    if config is not None:
        data['config'] = config

    if url is not None:
        data['url'] = url
    else:
        url = URL_PANEL_COMPONENT.format(component_name)

        if url not in _REGISTERED_COMPONENTS:
            hass.http.register_static_path(url, path)
            _REGISTERED_COMPONENTS.add(url)

        fprinted_url = URL_PANEL_COMPONENT_FP.format(component_name, md5)
        data['url'] = fprinted_url

    panels[url_path] = data

    # Register index view for this route if IndexView already loaded
    # Otherwise it will be done during setup.
    index_view = hass.data.get(DATA_INDEX_VIEW)

    if index_view:
        hass.http.app.router.add_route(
            'get', '/{}'.format(url_path), index_view.get)
        hass.http.app.router.add_route(
            'get', '/{}/{{extra:.+}}'.format(url_path), index_view.get)


def add_manifest_json_key(key, val):
    """Add a keyval to the manifest.json."""
    MANIFEST_JSON[key] = val


def setup(hass, config):
    """Set up the serving of the frontend."""
    hass.http.register_view(BootstrapView)
    hass.http.register_view(ManifestJSONView)

    if hass.http.development:
        sw_path = "home-assistant-polymer/build/service_worker.js"
    else:
        sw_path = "service_worker.js"

    hass.http.register_static_path("/service_worker.js",
                                   os.path.join(STATIC_PATH, sw_path), False)
    hass.http.register_static_path("/robots.txt",
                                   os.path.join(STATIC_PATH, "robots.txt"))
    hass.http.register_static_path("/static", STATIC_PATH)

    local = hass.config.path('www')
    if os.path.isdir(local):
        hass.http.register_static_path("/local", local)

    index_view = hass.data[DATA_INDEX_VIEW] = IndexView()
    hass.http.register_view(index_view)

    # Components have registered panels before frontend got setup.
    # Now register their urls.
    if DATA_PANELS in hass.data:
        for url_path in hass.data[DATA_PANELS]:
            hass.http.app.router.add_route(
                'get', '/{}'.format(url_path), index_view.get)
            hass.http.app.router.add_route(
                'get', '/{}/{{extra:.+}}'.format(url_path), index_view.get)
    else:
        hass.data[DATA_PANELS] = {}

    register_built_in_panel(hass, 'map', 'Map', 'mdi:account-location')

    for panel in ('dev-event', 'dev-info', 'dev-service', 'dev-state',
                  'dev-template', 'kiosk'):
        register_built_in_panel(hass, panel)

    themes = config.get(DOMAIN, {}).get(ATTR_THEMES)
    setup_themes(hass, themes)

    return True


def setup_themes(hass, themes):
    """Set up themes data and services."""
    hass.http.register_view(ThemesView)
    hass.data[DATA_DEFAULT_THEME] = DEFAULT_THEME
    if themes is None:
        hass.data[DATA_THEMES] = {}
        return

    hass.data[DATA_THEMES] = themes

    @callback
    def update_theme_and_fire_event():
        """Update theme_color in manifest."""
        name = hass.data[DATA_DEFAULT_THEME]
        themes = hass.data[DATA_THEMES]
        if name != DEFAULT_THEME and PRIMARY_COLOR in themes[name]:
            MANIFEST_JSON['theme_color'] = themes[name][PRIMARY_COLOR]
        else:
            MANIFEST_JSON['theme_color'] = DEFAULT_THEME_COLOR
        hass.bus.async_fire(EVENT_THEMES_UPDATED, {
            'themes': themes,
            'default_theme': name,
        })

    @callback
    def set_theme(call):
        """Set backend-prefered theme."""
        data = call.data
        name = data[CONF_NAME]
        if name == DEFAULT_THEME or name in hass.data[DATA_THEMES]:
            _LOGGER.info("Theme %s set as default", name)
            hass.data[DATA_DEFAULT_THEME] = name
            update_theme_and_fire_event()
        else:
            _LOGGER.warning("Theme %s is not defined.", name)

    @callback
    def reload_themes(_):
        """Reload themes."""
        path = find_config_file(hass.config.config_dir)
        new_themes = load_yaml_config_file(path)[DOMAIN].get(ATTR_THEMES, {})
        hass.data[DATA_THEMES] = new_themes
        if hass.data[DATA_DEFAULT_THEME] not in new_themes:
            hass.data[DATA_DEFAULT_THEME] = DEFAULT_THEME
        update_theme_and_fire_event()

    descriptions = load_yaml_config_file(
        os.path.join(os.path.dirname(__file__), 'services.yaml'))
    hass.services.register(DOMAIN, SERVICE_SET_THEME,
                           set_theme,
                           descriptions[SERVICE_SET_THEME],
                           SERVICE_SET_THEME_SCHEMA)
    hass.services.register(DOMAIN, SERVICE_RELOAD_THEMES, reload_themes,
                           descriptions[SERVICE_RELOAD_THEMES])


class BootstrapView(HomeAssistantView):
    """View to bootstrap frontend with all needed data."""

    url = '/api/bootstrap'
    name = 'api:bootstrap'

    @callback
    def get(self, request):
        """Return all data needed to bootstrap Home Assistant."""
        hass = request.app['hass']

        return self.json({
            'config': hass.config.as_dict(),
            'states': hass.states.async_all(),
            'events': api.async_events_json(hass),
            'services': api.async_services_json(hass),
            'panels': hass.data[DATA_PANELS],
        })


class IndexView(HomeAssistantView):
    """Serve the frontend."""

    url = '/'
    name = 'frontend:index'
    requires_auth = False
    extra_urls = ['/states', '/states/{extra}']

    def __init__(self):
        """Initialize the frontend view."""
        from jinja2 import FileSystemLoader, Environment

        self.templates = Environment(
            loader=FileSystemLoader(
                os.path.join(os.path.dirname(__file__), 'templates/')
            )
        )

    @asyncio.coroutine
    def get(self, request, extra=None):
        """Serve the index view."""
        hass = request.app['hass']

        if request.app[KEY_DEVELOPMENT]:
            core_url = '/static/home-assistant-polymer/build/core.js'
            compatibility_url = \
                '/static/home-assistant-polymer/build/compatibility.js'
            ui_url = '/static/home-assistant-polymer/src/home-assistant.html'
        else:
            core_url = '/static/core-{}.js'.format(
                FINGERPRINTS['core.js'])
            compatibility_url = '/static/compatibility-{}.js'.format(
                FINGERPRINTS['compatibility.js'])
            ui_url = '/static/frontend-{}.html'.format(
                FINGERPRINTS['frontend.html'])

        if request.path == '/':
            panel = 'states'
        else:
            panel = request.path.split('/')[1]

        if panel == 'states':
            panel_url = ''
        else:
            panel_url = hass.data[DATA_PANELS][panel]['url']

        no_auth = 'true'
        if hass.config.api.api_password:
            # require password if set
            no_auth = 'false'
            if is_trusted_ip(request):
                # bypass for trusted networks
                no_auth = 'true'

        icons_url = '/static/mdi-{}.html'.format(FINGERPRINTS['mdi.html'])
        template = yield from hass.async_add_job(
            self.templates.get_template, 'index.html')

        # pylint is wrong
        # pylint: disable=no-member
        # This is a jinja2 template, not a HA template so we call 'render'.
        resp = template.render(
            core_url=core_url, ui_url=ui_url,
            compatibility_url=compatibility_url, no_auth=no_auth,
            icons_url=icons_url, icons=FINGERPRINTS['mdi.html'],
            panel_url=panel_url, panels=hass.data[DATA_PANELS])

        return web.Response(text=resp, content_type='text/html')


class ManifestJSONView(HomeAssistantView):
    """View to return a manifest.json."""

    requires_auth = False
    url = '/manifest.json'
    name = 'manifestjson'

    @asyncio.coroutine
    def get(self, request):    # pylint: disable=no-self-use
        """Return the manifest.json."""
        msg = json.dumps(MANIFEST_JSON, sort_keys=True).encode('UTF-8')
        return web.Response(body=msg, content_type="application/manifest+json")


class ThemesView(HomeAssistantView):
    """View to return defined themes."""

    requires_auth = False
    url = '/api/themes'
    name = 'api:themes'

    @callback
    def get(self, request):
        """Return themes."""
        hass = request.app['hass']

        return self.json({
            'themes': hass.data[DATA_THEMES],
            'default_theme': hass.data[DATA_DEFAULT_THEME],
        })
