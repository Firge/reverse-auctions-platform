from decimal import Decimal
from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from .dadata import DadataError, PartyNotFoundError, find_party_by_inn
from .inn import INN_REGEX, is_valid_inn, normalize_inn
from .models import Auction, Bid, AuctionItem, ReverseEnglishAuction, CatalogItem, Profile, CatalogNode


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=20, required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    role = serializers.ChoiceField(choices=Profile.Role.choices, required=True)
    company_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    inn = serializers.CharField(max_length=12, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует.")
        return value.lower()

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Пользователь с таким именем уже существует.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except ValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate_inn(self, value):
        normalized = normalize_inn(value)
        if not normalized:
            return ""
        if not INN_REGEX.fullmatch(normalized) or not is_valid_inn(normalized):
            raise serializers.ValidationError("Введите корректный ИНН.")
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        inn = attrs.get("inn", "")
        if inn:
            try:
                party = find_party_by_inn(inn)
            except PartyNotFoundError as exc:
                raise serializers.ValidationError({"inn": str(exc)}) from exc
            except DadataError as exc:
                raise serializers.ValidationError({"inn": str(exc)}) from exc
            attrs["company_name"] = party["company_name"]
        return attrs

    def create(self, validated_data):
        role = validated_data.pop('role')
        company_name = validated_data.pop('company_name', '')
        inn = validated_data.pop('inn', '')
        with transaction.atomic():
            user = User.objects.create_user(
                username=validated_data['username'],
                email=validated_data['email'],
                password=validated_data['password'],
            )
            profile, _ = Profile.objects.get_or_create(user=user, defaults={'role': role})
            profile.role = role
            profile.company_name = company_name
            profile.inn = inn
            profile.save()
        return user


class AccountUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=20, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    role = serializers.ChoiceField(choices=Profile.Role.choices, required=False)
    company_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    inn = serializers.CharField(max_length=12, required=False, allow_blank=True)

    def validate_username(self, value):
        user = self.context["request"].user
        if User.objects.filter(username__iexact=value).exclude(id=user.id).exists():
            raise serializers.ValidationError("Пользователь с таким именем уже существует.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except ValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate_role(self, value):
        user = self.context["request"].user
        current_role = user.profile.role
        if current_role != value:
            raise serializers.ValidationError("Роль нельзя изменить.")
        return value

    def validate_inn(self, value):
        normalized = normalize_inn(value)
        if not normalized:
            return ""
        if not INN_REGEX.fullmatch(normalized) or not is_valid_inn(normalized):
            raise serializers.ValidationError("Введите корректный ИНН.")
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        inn = attrs.get("inn")
        if inn:
            try:
                party = find_party_by_inn(inn)
            except PartyNotFoundError as exc:
                raise serializers.ValidationError({"inn": str(exc)}) from exc
            except DadataError as exc:
                raise serializers.ValidationError({"inn": str(exc)}) from exc
            attrs["company_name"] = party["company_name"]
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        profile, _ = Profile.objects.get_or_create(user=instance)

        password = validated_data.pop("password", None)
        company_name = validated_data.pop("company_name", None)
        inn = validated_data.pop("inn", None)

        username = validated_data.get("username")
        if username is not None:
            instance.username = username
        if password:
            instance.set_password(password)
        instance.save()

        if company_name is not None:
            profile.company_name = company_name
        if inn is not None:
            profile.inn = inn
        profile.save()
        return instance


class BidSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bid
        fields = ['id', 'auction', 'bid', 'comment', 'status']


class CatalogNodeSerializer(serializers.ModelSerializer):
    has_children = serializers.SerializerMethodField()
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = CatalogNode
        fields = ('id', 'name', 'parent_id', 'has_children', 'items_count')

    def get_has_children(self, obj):
        return CatalogNode.objects.filter(parent=obj).exists()

    def get_items_count(self, obj):
        return CatalogItem.objects.filter(node=obj).count()


class CatalogItemSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source='node.name', read_only=True, allow_null=True)
    parent_node_id = serializers.IntegerField(source='node.parent_id', read_only=True, allow_null=True)
    parent_node_name = serializers.CharField(source='node.parent.name', read_only=True, allow_null=True)

    class Meta:
        model = CatalogItem
        fields = (
            'id',
            'code',
            'name',
            'unit',
            'price_release',
            'price_estimate',
            'node_id',
            'node_name',
            'parent_node_id',
            'parent_node_name',
            'source_id',
        )


class AuctionItemSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='catalog_item.id', read_only=True)
    code = serializers.CharField(source='catalog_item.code', read_only=True)
    name = serializers.CharField(source='catalog_item.name', read_only=True)
    unit = serializers.CharField(source='catalog_item.unit', read_only=True)

    class Meta:
        model = AuctionItem
        fields = ['id', 'code', 'name', 'unit', 'quantity']


class AuctionSerializer(serializers.ModelSerializer):
    auction_type = serializers.CharField(source='auction_type.model', read_only=True)
    specific = serializers.SerializerMethodField()
    lots = AuctionItemSerializer(source='items.all', many=True, read_only=True)

    class Meta:
        model = Auction
        fields = ['id', 'owner', 'title', 'description', 'start_price', 'current_price', 'start_date', 'end_date',
                  'status', 'auction_type', 'specific', 'lots', 'winner_bid', 'winner_determined_at']

    def get_specific(self, obj):
        if obj.specific_auction:
            return self.get_specific_serializer(obj.specific_auction).data
        return None

    def get_specific_serializer(self, specific_auction):
        serializers_map = {
            'reverseenglishauction': ReverseEnglishAuctionSerializer,
        }

        model_name = specific_auction._meta.model_name
        serializer_class = serializers_map.get(model_name)

        if serializer_class:
            return serializer_class(specific_auction)
        return None


class ReverseEnglishAuctionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReverseEnglishAuction
        fields = ['min_bid_decrement']


class AuctionCreateSerializerFactory:
    _registered_serializers = {}

    @classmethod
    def get_registered_names(cls):
        return list(cls._registered_serializers.keys())

    @classmethod
    def register(cls, name):
        def decorator(serializer_class):
            cls._registered_serializers[name] = serializer_class
            return serializer_class
        return decorator

    @classmethod
    def get_serializer(cls, name):
        return cls._registered_serializers.get(name, BaseAuctionCreateSerializer)


class BaseAuctionCreateSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField()
    start_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    auction_type = serializers.CharField()
    lots = serializers.ListField(child=serializers.DictField(), required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start_date = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        if start_date and end_date and end_date <= start_date:
            raise serializers.ValidationError({'end_date': 'Дата окончания должна быть позже даты начала.'})
        return attrs

    def validate_auction_type(self, value):
        registered_names = AuctionCreateSerializerFactory.get_registered_names()
        if value not in registered_names:
            raise serializers.ValidationError(f"Некорректный тип аукциона '{value}'. Поддерживаются: {registered_names}")
        return value

    def validate_lots(self, value):
        validated_lots = []
        for lot in value:
            if 'id' not in lot:
                raise serializers.ValidationError("У каждого лота должно быть поле 'id'.")
            if 'quantity' not in lot:
                raise serializers.ValidationError("У каждого лота должно быть поле 'quantity'.")

            try:
                lot_id = int(lot['id'])
                quantity = Decimal(lot['quantity'])
            except (ValueError, TypeError):
                raise serializers.ValidationError(f"Некорректный формат id или quantity в лоте: {lot}")
            if quantity <= 0:
                raise serializers.ValidationError(f"Количество для лота {lot_id} должно быть больше нуля.")
            if not CatalogItem.objects.filter(id=lot_id).exists():
                raise serializers.ValidationError(f"Позиция каталога с id {lot_id} не существует.")
            validated_lots.append({'id': lot_id, 'quantity': quantity})

        return validated_lots

    @property
    def common_fields(self):
        return 'title', 'description', 'start_price', 'start_date', 'end_date', 'auction_type'

    @property
    def specific_model(self):
        raise NotImplementedError("Должно быть реализовано в подклассе.")

    @property
    def specific_fields(self):
        raise NotImplementedError("Должно быть реализовано в подклассе.")

    def to_representation(self, instance):
        return AuctionSerializer(instance, context=self.context).data

    def _extract_data(self, validated_data):
        common_data = {}
        specific_data = {}

        for key, value in validated_data.items():
            if key in self.specific_fields:
                specific_data[key] = value
            elif key in self.common_fields:
                common_data[key] = value

        return common_data, specific_data

    @transaction.atomic
    def create(self, validated_data):
        lots_data = validated_data.pop('lots', [])
        common_data, specific_data = self._extract_data(validated_data)

        specific_auction = self.specific_model.objects.create(**specific_data)
        common_data['auction_type'] = ContentType.objects.get_for_model(self.specific_model)

        auction = Auction.objects.create(
            **common_data,
            owner=self.context['request'].user,
            object_id=specific_auction.id,
            specific_auction=specific_auction
        )

        if lots_data:
            AuctionItem.objects.bulk_create([
                AuctionItem(
                    auction=auction,
                    catalog_item_id=lot['id'],
                    quantity=lot['quantity'],
                )
                for lot in lots_data
            ])

        return auction

    @transaction.atomic
    def update(self, instance, validated_data):
        lots_data = validated_data.pop('lots', None)
        common_data, specific_data = self._extract_data(validated_data)

        new_auction_type = common_data.pop('auction_type')
        if new_auction_type is not None and new_auction_type != instance.auction_type.model:
            raise ValidationError('Изменение типа аукциона запрещено.')

        for attr, value in specific_data.items():
            setattr(instance.specific_auction, attr, value)

        for attr, value in common_data.items():
            setattr(instance, attr, value)

        instance.save()
        instance.specific_auction.save()

        if lots_data is not None:
            instance.items.all().delete()
            if lots_data:
                AuctionItem.objects.bulk_create([
                    AuctionItem(
                        auction=instance,
                        catalog_item_id=lot['id'],
                        quantity=lot['quantity'],
                    )
                    for lot in lots_data
                ])

        return instance


@AuctionCreateSerializerFactory.register("reverseenglishauction")
class ReverseEnglishAuctionCreateSerializer(BaseAuctionCreateSerializer):
    min_bid_decrement = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)

    @property
    def specific_model(self):
        return ReverseEnglishAuction

    @property
    def specific_fields(self):
        return ('min_bid_decrement',)
