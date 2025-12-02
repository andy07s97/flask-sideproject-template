from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Create the Limiter without binding storage yet;
# we’ll bind it in create_app() so we can read app.config.

# Make sure to use the keyword name "key_func"
limiter = Limiter(key_func=get_remote_address)
