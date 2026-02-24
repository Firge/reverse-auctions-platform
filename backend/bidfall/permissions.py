from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        action = getattr(view, "action", None)

        # Manual alias route `/api/auctions/<id>/bids/` uses class permissions.
        # Keep bid history owner-only, but allow the bid action for authenticated users.
        if action == "bids":
            return request.user and request.user.is_authenticated and obj.owner == request.user
        if action == "place_bid":
            return request.user and request.user.is_authenticated

        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.owner == request.user


class IsOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user
