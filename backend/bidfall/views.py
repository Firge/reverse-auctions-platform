from decimal import Decimal, InvalidOperation

from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, MethodNotAllowed
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from .serializers import (
    RegisterSerializer,
    AuctionSerializer,
    BidSerializer,
    AuctionCreateSerializerFactory,
    AccountUpdateSerializer,
)
from .models import Auction, Bid
from .permissions import IsOwnerOrReadOnly, IsOwner
from .auctions import AuctionStrategyFactory, determine_and_persist_winner


def sync_auction_runtime_status(auction: Auction):
    now = timezone.now()
    changed = False

    if auction.status == Auction.Status.PUBLISHED and auction.start_date <= now < auction.end_date:
        auction.status = Auction.Status.ACTIVE
        changed = True
    elif auction.status in (Auction.Status.PUBLISHED, Auction.Status.ACTIVE) and auction.end_date <= now:
        auction.status = Auction.Status.FINISHED
        changed = True

    if changed:
        auction.save(update_fields=["status"])
    if auction.status in (Auction.Status.FINISHED, Auction.Status.CLOSED):
        determine_and_persist_winner(auction)
    return auction


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def server_time_view(request):
    now = timezone.now()
    return Response({
        "server_time": now.isoformat(),
        "server_time_ms": int(now.timestamp() * 1000),
    })


@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def me_view(request):
    if request.method == 'PATCH':
        serializer = AccountUpdateSerializer(instance=request.user, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
    profile = getattr(request.user, 'profile', None)
    return Response({
        "id": request.user.id,
        "username": request.user.username,
        "email": request.user.email,
        "date_joined": request.user.date_joined,
        "profile": {
            "role": getattr(profile, "role", None),
            "company_name": getattr(profile, "company_name", ""),
            "inn": getattr(profile, "inn", ""),
            "rating": getattr(profile, "rating", None),
        },
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_auctions_view(request):
    auctions = Auction.objects.filter(owner=request.user).order_by('-end_date')
    return Response(AuctionSerializer(auctions, many=True).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_participating_auctions_view(request):
    auctions = Auction.objects.filter(bids__owner=request.user).distinct().order_by('-end_date')
    return Response(AuctionSerializer(auctions, many=True).data)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny, )

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response({
            "id": user.id,
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.profile.role,
            "rating": user.profile.rating,
            "created_at": user.date_joined,
        }, status=status.HTTP_201_CREATED)


class AuctionViewSet(viewsets.ModelViewSet):
    queryset = Auction.objects.all()
    serializer_class = AuctionSerializer
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)

    def get_queryset(self):
        qs = Auction.objects.all()
        if self.action == 'list':
            return qs.exclude(status=Auction.Status.DRAFT)

        user = self.request.user
        if not user.is_authenticated:
            return qs.exclude(status=Auction.Status.DRAFT)
        return qs.filter(Q(owner=user) | ~Q(status=Auction.Status.DRAFT))

    def get_serializer_class(self):
        if self.action == 'create':
            auction_type = self.request.data.get('auction_type')
            if auction_type:
                return AuctionCreateSerializerFactory.get_serializer(auction_type)
        if self.action in ('update', 'partial_update'):
            auction_type = self.request.data.get('auction_type')
            if auction_type:
                return AuctionCreateSerializerFactory.get_serializer(auction_type)
            try:
                instance = self.get_object()
            except Exception:
                instance = None
            if instance and instance.auction_type_id:
                return AuctionCreateSerializerFactory.get_serializer(instance.auction_type.model)
        return super().get_serializer_class()

    def get_object(self):
        auction = super().get_object()
        return sync_auction_runtime_status(auction)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def perform_create(self, serializer):
        role = getattr(getattr(self.request.user, 'profile', None), 'role', None)
        if role not in ('buyer', 'admin'):
            raise PermissionDenied("Only buyers or admins can create auctions.")
        serializer.save()

    def perform_update(self, serializer):
        auction = self.get_object()
        if auction.status != Auction.Status.DRAFT:
            raise PermissionDenied("Only draft auctions can be edited by the author.")

        serializer.save()

    @action(detail=False, methods=['get'])
    def active(self, request):
        for auction in Auction.objects.filter(status=Auction.Status.PUBLISHED):
            sync_auction_runtime_status(auction)
        active_auctions = Auction.objects.filter(status=Auction.Status.ACTIVE)
        serializer = AuctionSerializer(active_auctions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], permission_classes=[IsOwner])
    def bids(self, request, pk):
        auction = self.get_object()
        bids = Bid.objects.filter(auction=auction)
        serializer = BidSerializer(bids, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def close(self, request, pk):
        auction = self.get_object()
        if auction.owner_id != request.user.id:
            return Response({"error": "Only the auction owner can close this auction."}, status=status.HTTP_403_FORBIDDEN)

        if auction.status in (Auction.Status.CLOSED, Auction.Status.FINISHED, Auction.Status.CANCELED):
            return Response({"error": "Auction is already closed or finished."}, status=status.HTTP_400_BAD_REQUEST)

        auction.status = Auction.Status.CLOSED
        auction.save(update_fields=["status"])
        determine_and_persist_winner(auction)
        return Response(AuctionSerializer(auction).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def place_bid(self, request, pk):
        auction = self.get_object()
        auction = sync_auction_runtime_status(auction)
        if auction.status != Auction.Status.ACTIVE:
            return Response({"error": "Auction is not active."}, status=status.HTTP_400_BAD_REQUEST)
        if auction.owner_id == request.user.id:
            return Response({"error": "Auction owner cannot place bids."}, status=status.HTTP_403_FORBIDDEN)

        role = getattr(getattr(request.user, 'profile', None), 'role', None)
        if role not in ('supplier', 'admin'):
            return Response({"error": "Only suppliers or admins can place bids."}, status=status.HTTP_403_FORBIDDEN)

        raw_bid = request.data.get('bid', request.data.get('bid_amount'))
        try:
            bid_amount = Decimal(str(raw_bid))
        except (InvalidOperation, TypeError, ValueError):
            return Response({"error": "Invalid bid amount."}, status=status.HTTP_400_BAD_REQUEST)

        comment = request.data.get('comment', '')
        strategy = AuctionStrategyFactory.get_strategy(auction)
        try:
            strategy.validate_bid(auction, bid_amount)
        except ValueError as e:
            return Response({
                "error": str(e),
            }, status=status.HTTP_400_BAD_REQUEST)
        strategy.process_bid(auction, bid_amount, request.user, comment=comment)
        return Response({"success": True})

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def winner(self, request, pk):
        auction = self.get_object()
        if auction.status not in (Auction.Status.FINISHED, Auction.Status.CLOSED):
            return Response({
                "error": f"Auction is not finished yet.",
            }, status=status.HTTP_400_BAD_REQUEST)
        winner_bid = auction.winner_bid or determine_and_persist_winner(auction)
        if winner_bid is None:
            return Response({"error": "No bids found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BidSerializer(winner_bid).data)
