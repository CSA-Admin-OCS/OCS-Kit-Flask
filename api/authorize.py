from flask import request, current_app, g, abort
from flask_login import current_user, login_required
from functools import wraps
import jwt
from model.user import User
import roles as role_config

def identify():
    """Who is making this request: (user, None), or (None, (body, status)) with the answer to give.

    Flask-Login session first (fast), then the JWT cookie or Authorization header (stateless, for APIs).
    On success g.current_user is set. Shared by @auth_required and the global check in permissions.py,
    so both decide who the caller is in exactly the same way.

    Answers: 401 when there is no session and the token is missing, invalid, expired or from before a
    password change; 500 when decoding the token fails in some other way.
    """
    if current_user.is_authenticated:
        g.current_user = current_user
        return current_user, None

    token = request.cookies.get(current_app.config.get("JWT_TOKEN_NAME"))
    if not token:
        auth_header = request.headers.get('Authorization', request.headers.get('authorization', '')) or ''
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1].strip()
        elif auth_header:
            token = auth_header.strip()

    if not token:
        return None, ({
            "message": "Authentication required. No session or token found.",
            "data": None,
            "error": "Unauthorized"
        }, 401)

    try:
        data = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        user = User.query.filter_by(_uid=data["_uid"]).first()

        if user is None:
            return None, ({
                "message": "Invalid Authentication token!",
                "data": None,
                "error": "Unauthorized"
            }, 401)

        # Tokens issued before this field existed have no token_version claim
        # (treated as 0); reject if it doesn't match the account's current
        # value -- i.e. the password has changed since this token was issued.
        if data.get("token_version", 0) != (user.token_version or 0):
            return None, ({
                "message": "Token is no longer valid -- password has changed.",
                "data": None,
                "error": "Unauthorized"
            }, 401)

        g.current_user = user
        return user, None

    except jwt.ExpiredSignatureError:
        return None, ({"message": "Token has expired!", "data": None, "error": "Unauthorized"}, 401)
    except jwt.InvalidTokenError:
        return None, ({"message": "Invalid token!", "data": None, "error": "Unauthorized"}, 401)
    except Exception as e:
        return None, ({"message": "Something went wrong decoding the token!", "data": None, "error": str(e)}, 500)


def auth_required(roles=None):
    '''
    Guard one route: the caller must be signed in (session or JWT, see identify()), and when roles
    is given, must have one of those stored roles. Sets g.current_user for the route.

    Most routes need no decorator for access: who may make a request is decided once, before the
    route runs, by permissions.json (see permissions.py). Use this decorator when the route reads
    g.current_user, or to ask for something stricter than the file says.

    Args:
        roles: Stored role name, or a list/tuple of them. Take them from roles.py
               (e.g. roles.admin_role() or roles.staff_roles()), never a literal.
               If None, any authenticated user is allowed

    Possible error responses:
      A. 401 / Unauthorized: no session and token is missing or invalid
      B. 403 / Forbidden: user has insufficient permissions
      C. 500 / Internal Server Error: something went wrong with token decoding
    '''
    def decorator(func_to_guard):
        @wraps(func_to_guard)
        def decorated(*args, **kwargs):
            user, refusal = identify()
            if refusal:
                return refusal

            if roles:
                required_roles = list(roles) if isinstance(roles, (list, tuple)) else [roles]
                if not role_config.meets(user.role, required_roles):
                    return {
                        "message": f"Insufficient permissions. Required roles: {', '.join(required_roles)}",
                        "data": None,
                        "error": "Forbidden"
                    }, 403

            # If this is a CORS preflight request, return 200 OK immediately
            if request.method == 'OPTIONS':
                return ('', 200)

            return func_to_guard(*args, **kwargs)

        return decorated

    return decorator


# Alias for backward compatibility with existing code using token_required
def token_required(roles=None):
    '''
    Backward compatibility alias for auth_required.
    Existing code using @token_required will continue to work.
    '''
    return auth_required(roles)


def page_roles_required(allowed):
    """Decorator factory for server-rendered admin pages (Flask-Login session).
    allowed() returns the stored roles that may open the page. Anonymous users are
    redirected to the login page; logged-in users without one of the roles get 403."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if not role_config.meets(current_user.role, allowed()):
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


# Pages only the admin role may open (user deletion, password resets, ...)
admin_page_required = page_roles_required(lambda: (role_config.admin_role(),))
# Pages staff (e.g. Teacher / Manager / Editor) and admins may open (user list, sections)
staff_page_required = page_roles_required(role_config.staff_roles)
