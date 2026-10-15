from django.contrib import admin

from .models import (
    Appeal,
    ConsentRecord,
    DataRequest,
    HelpArticle,
    InsuranceClaim,
    Macro,
    TicketRating,
)

for model in (Appeal, ConsentRecord, DataRequest, HelpArticle, InsuranceClaim, Macro, TicketRating):
    admin.site.register(model)
