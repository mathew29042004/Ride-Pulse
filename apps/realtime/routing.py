from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/trips/<int:trip_id>/", consumers.TripConsumer.as_asgi()),
    path("ws/driver/", consumers.DriverConsumer.as_asgi()),
    path("ws/ops/", consumers.OpsConsumer.as_asgi()),
    path("ws/chat/", consumers.ChatConsumer.as_asgi()),
]
