"""Shape of the detector webhook body."""
from decimal import ROUND_HALF_UP

from rest_framework import serializers


class ImageSerializer(serializers.Serializer):
    bucket = serializers.CharField(max_length=222)
    object = serializers.CharField(max_length=1024)
    generation = serializers.RegexField(r'^\d{1,32}$')
    river = serializers.SlugField()
    satellite = serializers.CharField(max_length=60)
    captured_at = serializers.DateTimeField()


class ModelSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    version = serializers.CharField(max_length=40)


class DetectionSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90, coerce_to_string=False,
                               rounding=ROUND_HALF_UP)
    lon = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180, coerce_to_string=False,
                               rounding=ROUND_HALF_UP)
    confidence = serializers.FloatField(min_value=0, max_value=1)
    bbox = serializers.ListField(child=serializers.IntegerField(min_value=0), min_length=4, max_length=4)
    crop_uri = serializers.RegexField(r'^gs://[^/]+/.+', max_length=1024, required=False, allow_blank=True)


class DetectionWebhookSerializer(serializers.Serializer):
    image = ImageSerializer()
    model = ModelSerializer()
    detections = DetectionSerializer(many=True, max_length=500)
