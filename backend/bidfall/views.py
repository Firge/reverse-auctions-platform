from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import MethodNotAllowed
from django.contrib.auth.models import User
from django.db.models import Q

from .serializers import RegisterSerializer, AuctionSerializer, BidSerializer, AuctionCreateSerializerFactory
from .models import Auction, Bid
from .permissions import IsOwnerOrReadOnly, IsOwner
from .auctions import AuctionStrategyFactory


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny, )

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response({
            "email": user.email,
        }, status=status.HTTP_201_CREATED)


class AuctionViewSet(viewsets.ModelViewSet):
    queryset = Auction.objects.all()
    serializer_class = AuctionSerializer
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            auction_type = self.request.data.get('auction_type')
            return AuctionCreateSerializerFactory.get_serializer(auction_type)
        return super().get_serializer_class()

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    @action(detail=False, methods=['get'])
    def active(self, request):
        active_auctions = Auction.objects.filter(
            Q(status=Auction.Status.ACTIVE)
        )
        serializer = AuctionSerializer(active_auctions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], permission_classes=[IsOwner])
    def bids(self, request, pk):
        auction = self.get_object()
        bids = Bid.objects.filter(auction=auction)
        serializer = BidSerializer(bids, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def place_bid(self, request, pk):
        auction = self.get_object()
        strategy = AuctionStrategyFactory.get_strategy(auction)
        try:
            strategy.validate_bid(auction, request.data.get('bid'))
        except ValueError as e:
            return Response({
                "error": str(e),
            }, status.HTTP_400_BAD_REQUEST)
        strategy.process_bid(auction, request.data.get('bid'), request.user)
        return Response({"success": True})

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def winner(self, request, pk):
        auction = self.get_object()
        if auction.status != Auction.Status.FINISHED:
            return Response({
                "error": f"Auction is not finished yet.",
            }, status.HTTP_400_BAD_REQUEST)
        strategy = AuctionStrategyFactory.get_strategy(auction)
        return Response(BidSerializer(strategy.determine_winner(auction)).data)
