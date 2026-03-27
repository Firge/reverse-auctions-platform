from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from .serializers import (
    RegisterSerializer,
    AccountUpdateSerializer,
    AuctionSerializer,
    BidSerializer,
    AuctionCreateSerializerFactory
)
from .models import Auction, Bid, PaymentTransaction
from .permissions import IsOwnerOrReadOnly, IsOwner
from .auctions import AuctionStrategyFactory, finalize_auction_with_winner
from .payment import freeze_funds


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
        if self.action in ['create', 'update', 'partial_update']:
            auction_type = self.request.data.get('auction_type')
            return AuctionCreateSerializerFactory.get_serializer(auction_type)
        return super().get_serializer_class()

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def perform_create(self, serializer):
        role = getattr(getattr(self.request.user, 'profile', None), 'role', None)
        if role not in ('buyer', 'admin'):
            raise PermissionDenied("Only buyers can create auctions.")
        serializer.save()

    def perform_update(self, serializer):
        auction = self.get_object()
        if auction.status != Auction.Status.DRAFT:
            raise PermissionDenied("Only draft auctions can be edited by the author.")

        serializer.save()

    @action(detail=False, methods=['get'])
    def active(self, request):
        active_auctions = Auction.objects.filter(status=Auction.Status.ACTIVE)
        serializer = AuctionSerializer(active_auctions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def close(self, request, pk):
        auction = self.get_object()

        if auction.status in (Auction.Status.CLOSED, Auction.Status.FINISHED, Auction.Status.CANCELED):
            return Response({"error": "Auction is already closed or finished."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            auction.status = Auction.Status.CLOSED
            auction.save(update_fields=["status"])
            finalize_auction_with_winner(auction)
        return Response(AuctionSerializer(auction).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def publish(self, request, pk):
        auction = self.get_object()

        if auction.status != Auction.Status.DRAFT:
            return Response({"error": "Only draft auction can be published."}, status=status.HTTP_400_BAD_REQUEST)

        payment_data = freeze_funds(
            request.user.id,
            auction.id,
            description=f"Заморозка для публикации аукциона #{auction.id}"
        )
        PaymentTransaction.objects.create(
            user=request.user,
            auction=auction,
            type=PaymentTransaction.Type.AUCTION_CREATION_HOLD,
            payment_id=payment_data["payment_id"],
        )
        return Response({
            "message": "Waiting for confirmation.",
            "redirect_url": payment_data["confirmation_url"]
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticated])
    def bids(self, request, pk):
        if request.method == "GET":
            auction = self.get_object()
            bids_qs = Bid.objects.filter(auction=auction)
            bids_qs = bids_qs.exclude(
                status__in=[Bid.Status.PENDING, Bid.Status.CANCELED]
            )
            serializer = BidSerializer(bids_qs, many=True)
            return Response(serializer.data)
        return self.place_bid(request, pk)

    def place_bid(self, request, pk):
        auction = self.get_object()
        if auction.status != Auction.Status.ACTIVE:
            return Response({"error": "Auction is not active."}, status=status.HTTP_400_BAD_REQUEST)

        role = request.user.profile.role
        if role not in ('supplier', 'admin'):
            return Response({"error": "Only suppliers can place bids."}, status=status.HTTP_403_FORBIDDEN)

        raw_bid = request.data.get('bid', request.data.get('bid_amount'))
        try:
            bid_amount = Decimal(raw_bid)
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
        try:
            payment_data = freeze_funds(
                request.user.id,
                auction.id,
                description=f"Заморозка для участия в аукционе #{auction.id}"
            )
            bid = Bid.objects.create(
                auction=auction,
                owner=request.user,
                bid=bid_amount,
                comment=comment,
            )
            PaymentTransaction.objects.create(
                user=request.user,
                bid=bid,
                type=PaymentTransaction.Type.BID_PLACEMENT_HOLD,
                payment_id=payment_data["payment_id"],
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Waiting for confirmation.",
            "redirect_url": payment_data["confirmation_url"]
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def winner(self, request, pk):
        auction = self.get_object()
        if auction.status not in (Auction.Status.FINISHED, Auction.Status.CLOSED):
            return Response({
                "error": f"Auction is not finished yet.",
            }, status=status.HTTP_400_BAD_REQUEST)
        winner_bid = auction.winner_bid
        if winner_bid is None:
            return Response({"error": "No bids found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BidSerializer(winner_bid).data)
