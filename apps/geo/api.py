from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import City, Zone


class ZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zone
        fields = ["id", "code", "name", "center_lat", "center_lng", "radius_km", "is_airport"]


class CitySerializer(serializers.ModelSerializer):
    zones = ZoneSerializer(many=True, read_only=True)

    class Meta:
        model = City
        fields = ["id", "name", "slug", "state", "center_lat", "center_lng", "radius_km", "zones"]


class CityViewSet(viewsets.ReadOnlyModelViewSet):
    """Cities Ride Pulse operates in, with their zones."""

    queryset = City.objects.filter(is_active=True).prefetch_related("zones")
    serializer_class = CitySerializer
    permission_classes = [AllowAny]  # public: the sign-up form lists cities
    lookup_field = "slug"
    pagination_class = None


class PlaceSerializer(serializers.Serializer):
    name = serializers.CharField()
    address = serializers.CharField()
    category = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    city = serializers.CharField()


class PlaceSearchView(APIView):
    """Autocomplete for pickup and drop locations, plus reverse lookup for map pins."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Search text (2+ characters)"),
            OpenApiParameter("city", str, description="Limit to a city slug"),
            OpenApiParameter("lat", float, description="Reverse lookup latitude"),
            OpenApiParameter("lng", float, description="Reverse lookup longitude"),
        ],
        responses=PlaceSerializer(many=True),
        tags=["places"],
    )
    def get(self, request):
        params = request.query_params
        if "lat" in params and "lng" in params:
            try:
                lat, lng = float(params["lat"]), float(params["lng"])
            except ValueError:
                return Response([])
            city = services.city_for_point(lat, lng)
            return Response(
                [
                    {
                        "name": services.describe_point(lat, lng),
                        "address": city.name if city else "",
                        "category": "Pin",
                        "lat": lat,
                        "lng": lng,
                        "city": city.slug if city else "",
                    }
                ]
            )
        city = City.objects.filter(slug=params.get("city", "")).first()
        return Response(
            PlaceSerializer(services.search_places(params.get("q", ""), city=city), many=True).data
        )
