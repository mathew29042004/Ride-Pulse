from django.contrib import admin

from .models import Experiment, Exposure, FeatureFlag

admin.site.register(FeatureFlag)
admin.site.register(Experiment)
admin.site.register(Exposure)
