from django.contrib import admin
from . import models


admin.site.register(models.Auction)
admin.site.register(models.AuctionItem)
admin.site.register(models.Bid)
admin.site.register(models.CatalogItem)
admin.site.register(models.PaymentTransaction)
admin.site.register(models.Profile)
admin.site.register(models.ReverseEnglishAuction)
