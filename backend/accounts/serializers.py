from rest_framework import serializers

from accounts.models import AuditLog


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", allow_null=True)

    class Meta:
        model = AuditLog
        fields = ("id", "action", "actor", "ip_address", "details", "created_at")
