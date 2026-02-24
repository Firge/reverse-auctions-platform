from django.contrib import admin
from . import models


admin.site.register(models.Auction)
admin.site.register(models.AuctionItem)
admin.site.register(models.Bid)
admin.site.register(models.CatalogItem)
admin.site.register(models.Profile)
