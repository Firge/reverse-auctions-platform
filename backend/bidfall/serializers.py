import re

from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from .models import Auction, Bid, AuctionItem, ReverseEnglishAuction, Profile, CatalogItem


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=20, required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    role = serializers.ChoiceField(choices=Profile.Role.choices, required=True)
    company_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    inn = serializers.CharField(max_length=12, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise serializers.ValidationError("Password must contain letters and digits.")
        return value

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
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise serializers.ValidationError("Password must contain letters and digits.")
        return value

    def validate_role(self, value):
        user = self.context["request"].user
        current_role = getattr(getattr(user, "profile", None), "role", None)
        is_admin = user.is_superuser or current_role == Profile.Role.ADMIN
        if value == Profile.Role.ADMIN and not is_admin:
            raise serializers.ValidationError("Only admins can assign admin role.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        profile, _ = Profile.objects.get_or_create(user=instance)

        password = validated_data.pop("password", None)
        role = validated_data.pop("role", None)
        company_name = validated_data.pop("company_name", None)
        inn = validated_data.pop("inn", None)

        username = validated_data.get("username")
        if username is not None:
            instance.username = username
        if password:
            instance.set_password(password)
        instance.save()

        if role is not None:
            profile.role = role
        if company_name is not None:
            profile.company_name = company_name
        if inn is not None:
            profile.inn = inn
        profile.save()
        return instance


class BidSerializer(serializers.ModelSerializer):
    bid = serializers.DecimalField(max_digits=12, decimal_places=2, required=True)

    class Meta:
        model = Bid
        fields = '__all__'
        read_only_fields = ('owner', 'auction')

    def validate_bid(self, value):
        if value < 0:
            raise serializers.ValidationError('Bid must be greater than 0')
        auction = self.context.get('auction')
        if auction and value > auction.start_price:
            raise serializers.ValidationError('Bid cannot be greater than start price')
        return value

    def create(self, validated_data):
        return super().create(validated_data)


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
    catalog_items = AuctionItemSerializer(source='items.all', many=True, read_only=True)
    lots = AuctionItemSerializer(source='items.all', many=True, read_only=True)

    class Meta:
        model = Auction
        fields = ['id', 'owner', 'title', 'description', 'start_price', 'current_price', 'start_date', 'end_date', 'status',
                  'winner_bid', 'winner_determined_at',
                  'auction_type', 'specific', 'catalog_items', 'lots']

    def get_specific(self, obj):
        if obj.specific_auction:
            serializer = self.get_specific_serializer(obj.specific_auction)
            return serializer.data if serializer else None
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
    status = serializers.ChoiceField(
        choices=[Auction.Status.DRAFT, Auction.Status.PUBLISHED],
        required=False,
        default=Auction.Status.DRAFT,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start_date = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        if start_date and end_date and end_date <= start_date:
            raise serializers.ValidationError({'end_date': 'end_date must be later than start_date'})
        return attrs

    def validate_auction_type(self, value):
        registered_names = AuctionCreateSerializerFactory.get_registered_names()
        if value not in registered_names:
            raise serializers.ValidationError(f"Invalid auction type '{value}', supported: {registered_names}")
        return value

    def validate_lots(self, value):
        validated_lots = []
        for lot in value:
            if 'id' not in lot:
                raise serializers.ValidationError("Each lot must have an 'id' field")
            if 'quantity' not in lot:
                raise serializers.ValidationError("Each lot must have a 'quantity' field")
            try:
                lot_id = int(lot['id'])
                quantity = float(lot['quantity'])
            except (ValueError, TypeError):
                raise serializers.ValidationError(f"Invalid id or quantity format in lot: {lot}")
            if quantity <= 0:
                raise serializers.ValidationError(f"Quantity must be positive for lot {lot_id}")
            if not CatalogItem.objects.filter(id=lot_id).exists():
                raise serializers.ValidationError(f"Catalog item with id {lot_id} does not exist")
            validated_lots.append({'id': lot_id, 'quantity': quantity})
        return validated_lots

    @property
    def common_fields(self):
        return 'title', 'description', 'start_price', 'start_date', 'end_date', 'auction_type', 'status'

    @property
    def specific_model(self):
        raise NotImplementedError("Must be implemented by subclass")

    @property
    def specific_fields(self):
        raise NotImplementedError("Must be implemented by subclass")

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
        common_data.setdefault('current_price', common_data.get('start_price'))
        auction = Auction.objects.create(
            **common_data,
            owner=self.context['request'].user,
            object_id=specific_auction.id,
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

        new_auction_type = common_data.get('auction_type', instance.auction_type.model)
        old_auction_type = instance.auction_type.model

        if old_auction_type != new_auction_type:
            old_specific = instance.specific_auction
            new_specific = self.specific_model.objects.create(**specific_data)
            instance.auction_type = ContentType.objects.get_for_model(self.specific_model)
            instance.object_id = new_specific.id
            if old_specific:
                old_specific.delete()
        elif specific_data and instance.specific_auction:
            for attr, value in specific_data.items():
                setattr(instance.specific_auction, attr, value)
            instance.specific_auction.save()

        for attr, value in common_data.items():
            if attr != 'auction_type':
                setattr(instance, attr, value)
        if instance.current_price is None:
            instance.current_price = instance.start_price
        instance.save()

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
    min_bid_decrement = serializers.DecimalField(max_digits=12, decimal_places=2)

    @property
    def specific_model(self):
        return ReverseEnglishAuction

    @property
    def specific_fields(self):
        return ('min_bid_decrement',)
