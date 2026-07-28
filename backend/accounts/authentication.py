from __future__ import annotations

from rest_framework import authentication, exceptions

from accounts.models import ServiceCredential


class ServiceKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate trusted internal clients using a named, hashed API key."""

    keyword = "X-Service-Key"

    def authenticate(self, request: object) -> tuple[object, ServiceCredential] | None:
        client_id = request.headers.get("X-Service-Client")
        raw_key = request.headers.get(self.keyword)
        if client_id is None and raw_key is None:
            return None
        if not client_id or not raw_key:
            raise exceptions.AuthenticationFailed("Both service client and key are required.")

        try:
            credential = ServiceCredential.objects.select_related("user").get(
                client_id=client_id,
                is_active=True,
            )
        except ServiceCredential.DoesNotExist as error:
            raise exceptions.AuthenticationFailed("Invalid service credential.") from error

        if not credential.check_key(raw_key) or not credential.user.is_active:
            raise exceptions.AuthenticationFailed("Invalid service credential.")
        return credential.user, credential
