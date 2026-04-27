import os
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView

from .auctions import AuctionStrategyFactory, finalize_auction_with_winner
from .confirmation import update_confirmation_flow
from .dadata import DadataError, DadataNotConfiguredError, PartyNotFoundError, find_party_by_inn
from .inn import INN_REGEX, is_valid_inn, normalize_inn
from .serializers import (
    RegisterSerializer,
    AccountUpdateSerializer,
    AuctionSerializer,
    BidSerializer,
    AuctionCreateSerializerFactory, CatalogNodeSerializer, CatalogItemSerializer
)
from .models import Auction, Bid, PaymentTransaction, ConfirmationFlow, CatalogNode, CatalogItem
from .payment import freeze_funds
from .permissions import IsOwnerOrReadOnly, IsOwner


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
            raise PermissionDenied("Только покупатели могут создавать аукционы.")
        serializer.save()

    def perform_update(self, serializer):
        auction = self.get_object()
        if auction.status != Auction.Status.DRAFT:
            raise PermissionDenied("Только черновик может редактироваться автором.")

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
            return Response({"error": "Аукцион уже закрыт или завершён."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            auction.status = Auction.Status.CLOSED
            auction.save(update_fields=["status"])
            finalize_auction_with_winner(auction)
        return Response(AuctionSerializer(auction).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def publish(self, request, pk):
        auction = self.get_object()

        if auction.status != Auction.Status.DRAFT:
            return Response({"error": "Опубликовать можно только черновик аукциона."}, status=status.HTTP_400_BAD_REQUEST)

        base_url = request.build_absolute_uri('/')
        return_url = base_url + f'auction/{auction.id}'
        payment_amount = Decimal(auction.start_price) * Decimal(os.getenv("PAYMENT_AUCTION_FORFEIT_PERCENT", 5)) / Decimal(100)
        payment_data = freeze_funds(
            request.user.id,
            auction.id,
            amount=payment_amount,
            description=f"Заморозка для публикации аукциона #{auction.id}",
            return_url=return_url
        )
        PaymentTransaction.objects.create(
            user=request.user,
            auction=auction,
            type=PaymentTransaction.Type.AUCTION_CREATION_HOLD,
            payment_id=payment_data["payment_id"],
        )
        return Response({
            "message": "Ожидается подтверждение.",
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
            return Response({"error": "Аукцион не активен."}, status=status.HTTP_400_BAD_REQUEST)

        role = request.user.profile.role
        if role not in ('supplier', 'admin'):
            return Response({"error": "Только поставщики могут делать ставки."}, status=status.HTTP_403_FORBIDDEN)

        raw_bid = request.data.get('bid', request.data.get('bid_amount'))
        try:
            bid_amount = Decimal(raw_bid)
        except (InvalidOperation, TypeError, ValueError):
            return Response({"error": "Некорректная сумма ставки."}, status=status.HTTP_400_BAD_REQUEST)

        comment = request.data.get('comment', '')
        strategy = AuctionStrategyFactory.get_strategy(auction)
        try:
            strategy.validate_bid(auction, bid_amount)
        except ValueError as e:
            return Response({
                "error": str(e),
            }, status=status.HTTP_400_BAD_REQUEST)
        try:
            base_url = request.build_absolute_uri('/')
            return_url = base_url + f'auction/{auction.id}'
            payment_amount = Decimal(auction.start_price) * Decimal(os.getenv("PAYMENT_BID_FORFEIT_PERCENT", 5)) / Decimal(100)
            payment_data = freeze_funds(
                request.user.id,
                auction.id,
                amount=payment_amount,
                description=f"Заморозка для участия в аукционе #{auction.id}",
                return_url=return_url
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
            "message": "Ожидается подтверждение.",
            "redirect_url": payment_data["confirmation_url"]
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def winner(self, request, pk):
        auction = self.get_object()
        if auction.status not in (Auction.Status.FINISHED, Auction.Status.CLOSED):
            return Response({
                "error": "Аукцион ещё не завершён.",
            }, status=status.HTTP_400_BAD_REQUEST)
        winner_bid = auction.winner_bid
        if winner_bid is None:
            return Response({"error": "Победитель не найден."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BidSerializer(winner_bid).data)

    @action(detail=True, methods=['post'], permission_classes=[IsOwner], url_path="confirm-creator")
    def confirm_creator(self, request, pk):
        auction = self.get_object()
        if auction.status not in (Auction.Status.FINISHED, Auction.Status.CLOSED):
            return Response({
                "error": "Аукцион ещё не завершён.",
            }, status=status.HTTP_400_BAD_REQUEST)

        confirmation = ConfirmationFlow.objects.filter(auction=auction).first()
        if not confirmation:
            return Response({"error": "Подтверждение не найдено."}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            confirmation = ConfirmationFlow.objects.select_for_update().get(pk=confirmation.pk)

            if confirmation.creator_signed_at is not None:
                return Response(
                    {"error": "Заказчик уже подписал подтверждение."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if timezone.now() > confirmation.signing_deadline:
                return Response(
                    {"error": "Срок подписания истёк."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            confirmation.creator_signed_at = timezone.now()
            confirmation.save(update_fields=['creator_signed_at'])

            update_confirmation_flow(confirmation)

        return Response({"status": "Подтверждение заказчика успешно сохранено."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated], url_path="confirm-winner")
    def confirm_winner(self, request, pk):
        auction = self.get_object()
        if auction.status not in (Auction.Status.FINISHED, Auction.Status.CLOSED):
            return Response({
                "error": "Аукцион ещё не завершён.",
            }, status=status.HTTP_400_BAD_REQUEST)

        winner_bid = auction.winner_bid
        if winner_bid is None:
            return Response({"error": "Победитель не найден."}, status=status.HTTP_404_NOT_FOUND)

        if request.user != winner_bid.owner:
            raise PermissionDenied("Подтвердить результат может только победитель.")

        confirmation = ConfirmationFlow.objects.filter(auction=auction).first()
        if not confirmation:
            return Response({"error": "Подтверждение не найдено."}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            confirmation = ConfirmationFlow.objects.select_for_update().get(pk=confirmation.pk)

            if confirmation.winner_signed_at is not None:
                return Response(
                    {"error": "Победитель уже подписал подтверждение."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if timezone.now() > confirmation.signing_deadline:
                return Response(
                    {"error": "Срок подписания истёк."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            confirmation.winner_signed_at = timezone.now()
            confirmation.save(update_fields=['winner_signed_at'])

            update_confirmation_flow(confirmation)

        return Response({"status": "Подтверждение победителя успешно сохранено."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated], url_path="confirmation")
    def confirmation_status(self, request, pk):
        auction = self.get_object()
        user = request.user

        if user != auction.owner and (not auction.winner_bid or user != auction.winner_bid.owner):
            raise PermissionDenied("Статус подтверждения может смотреть только создатель аукциона или победитель.")

        confirmation = ConfirmationFlow.objects.filter(auction=auction).first()
        if not confirmation:
            return Response({"error": "Подтверждение не найдено."}, status=status.HTTP_404_NOT_FOUND)

        data = {
            "creator_signed_at": confirmation.creator_signed_at.isoformat() if confirmation.creator_signed_at else None,
            "winner_signed_at": confirmation.winner_signed_at.isoformat() if confirmation.winner_signed_at else None,
            "signing_deadline": confirmation.signing_deadline.isoformat(),
            "status": confirmation.status if confirmation else None,
        }
        return Response(data)


class CatalogNodeListView(generics.ListAPIView):
    serializer_class = CatalogNodeSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = CatalogNode.objects.all()
        parent_id = self.request.query_params.get('parent_id')
        if parent_id is not None:
            queryset = queryset.filter(parent_id=parent_id)
        else:
            queryset = queryset.filter(parent__isnull=True)

        q = self.request.query_params.get('q')
        if q:
            queryset = queryset.filter(name__icontains=q)

        return queryset


class CatalogItemListView(generics.ListAPIView):
    serializer_class = CatalogItemSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = CatalogItem.objects.select_related("node", "node__parent").all()

        q = self.request.query_params.get('q')
        if q:
            queryset = queryset.filter(Q(code__icontains=q) | Q(name__icontains=q))

        node_id = self.request.query_params.get('node_id')
        if node_id is not None:
            queryset = queryset.filter(node_id=node_id)

        source_id = self.request.query_params.get('source_id')
        if source_id is not None:
            queryset = queryset.filter(source_id=source_id)

        return queryset


class CatalogItemByIdsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ids_param = request.query_params.get('ids')
        if not ids_param:
            return Response({"error": "Параметр ids обязателен."}, status=400)

        try:
            ids = [int(x.strip()) for x in ids_param.split(',')]
        except ValueError:
            return Response({"error": "Некорректный формат ids."}, status=400)

        items = CatalogItem.objects.select_related('node', 'node__parent').filter(id__in=ids)
        serializer = CatalogItemSerializer(items, many=True)
        return Response(serializer.data)


class PartyLookupByInnView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw_inn = request.data.get("inn", "")
        inn = normalize_inn(raw_inn)
        if not inn:
            return Response({"inn": ["ИНН обязателен."]}, status=status.HTTP_400_BAD_REQUEST)
        if not INN_REGEX.fullmatch(inn) or not is_valid_inn(inn):
            return Response({"inn": ["Введите корректный ИНН."]}, status=status.HTTP_400_BAD_REQUEST)

        try:
            party = find_party_by_inn(inn)
        except PartyNotFoundError as exc:
            return Response({"inn": [str(exc)]}, status=status.HTTP_404_NOT_FOUND)
        except DadataNotConfiguredError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except DadataError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(party, status=status.HTTP_200_OK)
