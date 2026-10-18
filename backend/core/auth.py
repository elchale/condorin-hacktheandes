"""Reading `Authorization: Bearer <token>`, shared by the webhook, the panel routes and the SPA session."""


def bearer_token(request) -> str | None:
    """The token of `Authorization: Bearer <token>`, or None when the header is absent or another scheme."""
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    token = token.strip()
    if scheme.lower() != 'bearer' or not token:
        return None
    return token
