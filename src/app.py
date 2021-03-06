import argparse
import datetime
import logging
import threading

from flask import Flask

from feed_utils.populate import prepare_pipelines_for_batch
from init_globals import init_globals
from utils.settings_loader import load_settings
from utils.flask_customization import customize_flask, customize_logger
from views.redirects import register_episode_redirect, register_article_redirect
from views.web_api import register_api_routes
from views.web_feed import register_feed_routes

app = Flask(__name__)

settings = load_settings()

global_values = (None, None)
create_global_lock = threading.RLock()


def get_global_func(*args, **kwargs):
    return global_values[0].get(*args, **kwargs)


def update_global_if_stale():
    global global_values
    with create_global_lock:
        global_dict, expires_at = global_values

        def has_expired():
            return datetime.datetime.now(datetime.timezone.utc) > expires_at

        if global_dict is None or has_expired():
            logger.info("global_values is stale, creating anew…")
            if global_dict:
                global_dict['requests'].close()
            new_global_dict = dict()
            init_globals(new_global_dict, settings, get_global_func)
            prepare_pipelines_for_batch(new_global_dict['processors']['show'])
            prepare_pipelines_for_batch(new_global_dict['processors']['episode'])

            now = datetime.datetime.now(datetime.timezone.utc)
            ttl = datetime.timedelta(seconds=settings['caching']['source_data_ttl'])
            new_expire_time = now + ttl

            global_values = (new_global_dict, new_expire_time)
        else:
            logger.debug("keeping global_values")


customize_logger()
# Hack: logger doesn't seem to work unless something is logged to the root
# logger
logging.info("Starting up podkast.radiorevolt.no application")
logger = logging.getLogger(__name__)
update_global_if_stale()
customize_flask(
    app,
    update_global_if_stale,
    official_website=settings['web']['official_website'],
    debug=settings.get('debug', False),
)

register_api_routes(app, settings, get_global_func)
register_episode_redirect(app, settings, get_global_func)
register_article_redirect(app, settings, get_global_func)
register_feed_routes(app, settings, get_global_func)


def parse_cli_arguments():
    parser = argparse.ArgumentParser(description="Run a server suitable for development purposes.")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="Activate debugging, overriding the option in webserver/settings.py "
                             "(you shouldn't use this script in production, but especially not with"
                             " this option!! You might reveal secret information to others.)")
    parser.add_argument("--port", "-p", default=5000, type=int,
                        help="Port to run the server on.")
    parser.add_argument("host", nargs="?", default="127.0.0.1", help="Accept connections for this host. "
                                                                     "Set to 0.0.0.0 to enable connections from anywhere (not safe!). "
                                                                     "Defaults to 127.0.0.1, which means only connections from this computer.")
    return parser, parser.parse_args()


def main():
    parser, args = parse_cli_arguments()
    host = args.host
    port = args.port

    if args.debug:
        app.debug = True
    app.run(host=host, port=port)

# Try to create a feed, so that any configuration errors are obvious (and
# SystemD marks the service as failed).
app.testing = True
test_client = app.test_client()
test_client.get('/nerdeprat')

app.testing = False

if __name__ == '__main__':
    main()
