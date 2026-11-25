"""Remember a lookup for the rest of one request, so a page that needs the same row in several places
(the campus settings, the signed-in user's profile) reads it from the database once.

Values live only until the response is sent. Outside a request (management commands, tests that call a
function directly) nothing is remembered and every call reads the database as before.
"""
from contextvars import ContextVar

_values: ContextVar[dict | None] = ContextVar('request_memo', default=None)


def remember(key, load):
    """Return load(), reusing the value from earlier in this request if there is one."""
    values = _values.get()
    if values is None:
        return load()
    if key not in values:
        values[key] = load()
    return values[key]


def forget(key):
    """Drop a remembered value, e.g. after the row it came from was changed."""
    values = _values.get()
    if values is not None:
        values.pop(key, None)


class RequestMemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _values.set({})
        try:
            return self.get_response(request)
        finally:
            _values.reset(token)
