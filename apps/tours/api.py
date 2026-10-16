"""Tours: the catalogue and booking (riders), the driver's assigned tours, and ops."""

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet
from apps.core.exceptions import ActionNotPermitted
from apps.pricing.models import RideType

from . import services
from .models import BookingStatus, TourBooking, TourCategory, TourPackage


class StopSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    name = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    minutes = serializers.IntegerField()
    note = serializers.CharField()


class PackageSerializer(serializers.ModelSerializer):
    city = serializers.CharField(source="city.slug")
    city_name = serializers.CharField(source="city.name")
    category_label = serializers.CharField(source="get_category_display")
    rating = serializers.FloatField(allow_null=True)
    stops = StopSerializer(many=True)
    from_price = serializers.SerializerMethodField()
    hours = serializers.SerializerMethodField()
    km = serializers.SerializerMethodField()

    class Meta:
        model = TourPackage
        fields = [
            "slug",
            "name",
            "tagline",
            "category",
            "category_label",
            "city",
            "city_name",
            "days",
            "start_time",
            "rating",
            "rating_count",
            "price_adjust_percent",
            "is_active",
            "stops",
            "from_price",
            "hours",
            "km",
        ]

    def _route(self, package):
        cache = self.context.setdefault("routes", {})
        if package.pk not in cache:
            cache[package.pk] = services.route(package)
        return cache[package.pk]

    def get_from_price(self, package) -> str:
        from apps.pricing.models import FareRule

        if "mini" not in self.context:
            mini = RideType.objects.get(code="MINI")
            self.context["mini"] = mini
            # Every city's Mini booking fee in one query (not one per package).
            self.context["fees"] = dict(
                FareRule.objects.filter(ride_type=mini, is_active=True).values_list(
                    "city_id", "booking_fee"
                )
            )
        fee = self.context["fees"].get(package.city_id)
        return str(services.tour_fare(package, self.context["mini"], booking_fee=fee).total)

    def get_hours(self, package) -> float:
        return self._route(package)["hours"]

    def get_km(self, package) -> str:
        return str(self._route(package)["km"])


class BookSerializer(serializers.Serializer):
    ride_type = serializers.SlugRelatedField(slug_field="code", queryset=RideType.objects.all())
    depart_at = serializers.DateTimeField()
    pickup_lat = serializers.FloatField()
    pickup_lng = serializers.FloatField()
    pickup_address = serializers.CharField(required=False, allow_blank=True, max_length=255)
    group_size = serializers.IntegerField(min_value=1, max_value=8, default=1)
    payment_method = serializers.CharField(required=False, default="UPI")


class BookingSerializer(serializers.ModelSerializer):
    package = serializers.SerializerMethodField()
    ride_type = serializers.CharField(source="ride_type.code")
    status_label = serializers.CharField(source="get_status_display")
    driver = serializers.SerializerMethodField()
    rider = serializers.SerializerMethodField()
    earning = serializers.SerializerMethodField()

    class Meta:
        model = TourBooking
        fields = [
            "id",
            "reference",
            "package",
            "ride_type",
            "depart_at",
            "pickup_lat",
            "pickup_lng",
            "pickup_address",
            "group_size",
            "price",
            "fare",
            "status",
            "status_label",
            "driver",
            "rider",
            "earning",
            "trip",
            "progress",
            "cancellation_fee",
            "rating",
            "review",
            "created_at",
        ]

    def get_package(self, booking) -> dict:
        p = booking.package
        return {
            "slug": p.slug,
            "name": p.name,
            "city_name": p.city.name,
            "days": p.days,
            "stops": [
                {
                    "order": s.order,
                    "name": s.name,
                    "minutes": s.minutes,
                    "note": s.note,
                    "lat": s.lat,
                    "lng": s.lng,
                }
                for s in p.stops.all()
            ],
        }

    def get_driver(self, booking) -> dict | None:
        d = booking.driver
        if d is None:
            return None
        vehicle = d.active_vehicle
        return {
            "name": d.name,
            "rating": str(d.rating),
            "phone": d.user.phone if booking.status == BookingStatus.STARTED else "",
            "vehicle": str(vehicle) if vehicle else "",
        }

    def get_rider(self, booking) -> dict | None:
        user = self.context["request"].user
        if user.is_rider:
            return None
        return {"name": booking.rider.user.get_full_name()}

    def get_earning(self, booking) -> str | None:
        user = self.context["request"].user
        return None if user.is_rider else booking.fare.get("driver_earning")


def _bookings():
    return TourBooking.objects.select_related(
        "package__city", "ride_type", "driver__user", "rider__user"
    ).prefetch_related("package__stops", "driver__vehicles")


class TourViewSet(BaseViewSet):
    """Riders browse and book; drivers see the tours assigned to them."""

    lookup_field = "slug"
    rider_actions = ("list", "retrieve", "book", "bookings", "cancel", "rate")
    driver_actions = ("assigned", "decline", "start", "stop")
    capabilities = {"list": Cap.TOURS_MANAGE, "retrieve": Cap.TOURS_MANAGE}

    def get_queryset(self):
        return (
            TourPackage.objects.filter(is_active=True)
            .select_related("city")
            .prefetch_related("stops")
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("city", str, required=False),
            OpenApiParameter("category", str, required=False, enum=TourCategory.values),
        ],
        responses=PackageSerializer(many=True),
    )
    def list(self, request):
        packages = self.get_queryset()
        if city := request.query_params.get("city"):
            packages = packages.filter(city__slug=city)
        if category := request.query_params.get("category"):
            packages = packages.filter(category=category)
        return Response(PackageSerializer(packages, many=True, context={}).data)

    @extend_schema(responses=PackageSerializer)
    def retrieve(self, request, slug=None):
        package = get_object_or_404(self.get_queryset(), slug=slug)
        data = PackageSerializer(package, context={}).data
        data["quotes"] = services.quotes(package)
        return Response(data)

    @extend_schema(request=BookSerializer, responses={201: BookingSerializer})
    @action(detail=True, methods=["post"])
    def book(self, request, slug=None):
        package = get_object_or_404(self.get_queryset(), slug=slug)
        data = BookSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        booking = services.book(
            rider=request.user.rider_profile,
            package=package,
            ride_type=v["ride_type"],
            depart_at=v["depart_at"],
            pickup=(v["pickup_lat"], v["pickup_lng"]),
            pickup_address=v.get("pickup_address", ""),
            group_size=v["group_size"],
            payment_method=v["payment_method"],
        )
        booking = _bookings().get(pk=booking.pk)
        return Response(
            BookingSerializer(booking, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses=BookingSerializer(many=True))
    @action(detail=False, methods=["get"])
    def bookings(self, request):
        rows = _bookings().filter(rider=request.user.rider_profile)[:50]
        return Response(BookingSerializer(rows, many=True, context={"request": request}).data)

    def _mine(self, request, pk):
        booking = get_object_or_404(_bookings(), pk=pk)
        if request.user.is_rider and booking.rider.user_id != request.user.pk:
            raise ActionNotPermitted("That isn't your tour.")
        if request.user.is_driver:
            me = request.user.driver_profile.pk
            if me not in (booking.driver_id, booking.trip.driver_id if booking.trip else None):
                raise ActionNotPermitted("That isn't your tour.")
        return booking

    def _respond(self, request, booking):
        booking = _bookings().get(pk=booking.pk)
        return Response(BookingSerializer(booking, context={"request": request}).data)

    @extend_schema(request=None, responses=BookingSerializer)
    @action(detail=False, methods=["post"], url_path=r"bookings/(?P<pk>\d+)/cancel")
    def cancel(self, request, pk=None):
        return self._respond(request, services.cancel(self._mine(request, pk), user=request.user))

    @extend_schema(request=OpenApiTypes.OBJECT, responses=BookingSerializer)
    @action(detail=False, methods=["post"], url_path=r"bookings/(?P<pk>\d+)/rate")
    def rate(self, request, pk=None):
        booking = services.rate(
            self._mine(request, pk),
            user=request.user,
            stars=int(request.data.get("stars", 0)),
            review=str(request.data.get("review", "")),
        )
        return self._respond(request, booking)

    # --- Drivers -------------------------------------------------------------------------

    @extend_schema(responses=BookingSerializer(many=True))
    @action(detail=False, methods=["get"])
    def assigned(self, request):
        driver = request.user.driver_profile
        rows = (
            _bookings()
            .filter(
                Q(driver=driver) | Q(trip__driver=driver),
                status__in=[BookingStatus.ASSIGNED, BookingStatus.STARTED],
                depart_at__gte=timezone.now() - timedelta(days=3),
            )
            .order_by("depart_at")
        )
        return Response(BookingSerializer(rows, many=True, context={"request": request}).data)

    @extend_schema(request=None, responses=BookingSerializer)
    @action(detail=False, methods=["post"], url_path=r"bookings/(?P<pk>\d+)/decline")
    def decline(self, request, pk=None):
        booking = services.decline(self._mine(request, pk), driver=request.user.driver_profile)
        return Response({"id": booking.pk, "status": booking.status})

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"bookings/(?P<pk>\d+)/start")
    def start(self, request, pk=None):
        trip = services.start(
            self._mine(request, pk),
            driver=request.user.driver_profile,
            lat=float(request.data.get("lat")),
            lng=float(request.data.get("lng")),
        )
        return Response({"trip_id": trip.pk})

    @extend_schema(request=OpenApiTypes.OBJECT, responses=BookingSerializer)
    @action(detail=False, methods=["post"], url_path=r"bookings/(?P<pk>\d+)/stop")
    def stop(self, request, pk=None):
        booking = services.mark_stop(
            self._mine(request, pk),
            driver=request.user.driver_profile,
            order=int(request.data.get("order", 0)),
            event=str(request.data.get("event", "")),
        )
        return self._respond(request, booking)


class PackageUpdateSerializer(serializers.Serializer):
    is_active = serializers.BooleanField(required=False)
    price_adjust_percent = serializers.IntegerField(required=False, min_value=-30, max_value=50)


class TourOpsViewSet(BaseViewSet):
    """Ops: the catalogue with bookings and revenue, upcoming tours, unassigned ones."""

    capabilities = {"*": Cap.TOURS_MANAGE}

    @extend_schema(
        parameters=[OpenApiParameter("city", int, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def overview(self, request):
        city = request.query_params.get("city")
        now = timezone.now()
        packages = TourPackage.objects.select_related("city").prefetch_related("stops")
        bookings = _bookings()
        if city:
            packages, bookings = (
                packages.filter(city_id=city),
                bookings.filter(package__city_id=city),
            )
        per_package = bookings.values("package_id").annotate(
            n=Count("pk"),
            done=Count("pk", filter=Q(status=BookingStatus.COMPLETED)),
            upcoming=Count(
                "pk",
                filter=Q(
                    status__in=[BookingStatus.BOOKED, BookingStatus.ASSIGNED], depart_at__gte=now
                ),
            ),
            revenue=Sum("price", filter=Q(status=BookingStatus.COMPLETED)),
        )
        stats = {
            r["package_id"]: (r["n"], r["done"], r["upcoming"], r["revenue"]) for r in per_package
        }
        rows = []
        shared: dict = {}  # one car type and fee lookup for the whole list
        for p in packages:
            n, done, upcoming, revenue = stats.get(p.pk, (0, 0, 0, None))
            rows.append(
                {
                    **PackageSerializer(p, context=shared).data,
                    "bookings": n,
                    "completed": done,
                    "upcoming": upcoming,
                    "revenue": str(revenue or 0),
                }
            )
        soon = bookings.filter(
            status__in=[BookingStatus.BOOKED, BookingStatus.ASSIGNED, BookingStatus.STARTED],
            depart_at__lte=now + timedelta(days=7),
        ).order_by("depart_at")[:100]
        return Response(
            {
                "packages": rows,
                "upcoming": BookingSerializer(soon, many=True, context={"request": request}).data,
                "unassigned_24h": bookings.filter(
                    status=BookingStatus.BOOKED, depart_at__lte=now + timedelta(hours=24)
                ).count(),
                "completed_30d": bookings.filter(
                    status=BookingStatus.COMPLETED, depart_at__gte=now - timedelta(days=30)
                ).count(),
                "revenue_30d": str(
                    bookings.filter(
                        status=BookingStatus.COMPLETED, depart_at__gte=now - timedelta(days=30)
                    ).aggregate(s=Sum("price"))["s"]
                    or 0
                ),
                "cancelled_30d": bookings.filter(
                    status=BookingStatus.CANCELLED, created_at__gte=now - timedelta(days=30)
                ).count(),
            }
        )

    @extend_schema(request=PackageUpdateSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"packages/(?P<slug>[\w-]+)")
    def package(self, request, slug=None):
        package = get_object_or_404(TourPackage, slug=slug)
        data = PackageUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        for field, value in data.validated_data.items():
            setattr(package, field, value)
        package.save(update_fields=list(data.validated_data) or None)
        return Response(PackageSerializer(package, context={}).data)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"bookings/(?P<pk>\d+)/assign")
    def assign(self, request, pk=None):
        booking = services.assign(get_object_or_404(TourBooking, pk=pk))
        return Response({"status": booking.status, "driver": booking.driver_id})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"bookings/(?P<pk>\d+)/cancel")
    def cancel(self, request, pk=None):
        booking = services.cancel(get_object_or_404(TourBooking, pk=pk), user=request.user)
        return Response({"status": booking.status})
