# -*- coding: utf-8 -*-
"""
Serializers for settings app
"""

from rest_framework import serializers

class SettingSerializer(serializers.Serializer):
    key = serializers.CharField()
    value = serializers.CharField()
    description = serializers.CharField(required=False)
    category = serializers.CharField(required=False)