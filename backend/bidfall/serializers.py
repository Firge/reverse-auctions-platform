from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import Auction, Bid, AuctionItem, ReverseEnglishAuction, CatalogItem


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=20, required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )


class BidSerializer(serializers.ModelSerializer):
    bid = serializers.DecimalField(max_digits=12, decimal_places=2, required=True)
    comment = serializers.CharField()

    class Meta:
        model = Bid
        fields = '__all__'
        read_only_fields = ('owner', 'auction')

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
    lots = AuctionItemSerializer(source='items.all', many=True, read_only=True)

    class Meta:
        model = Auction
        fields = ['id', 'owner', 'title', 'description', 'start_price', 'current_price', 'start_date', 'end_date', 'status',
                  'auction_type', 'specific', 'lots']

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
    title = serializers.CharField(required=True)
    description = serializers.CharField(required=True)
    start_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=True)
    start_date = serializers.DateTimeField(required=True)
    end_date = serializers.DateTimeField(required=True)
    auction_type = serializers.CharField(required=True)
    lots = serializers.ListField(child=serializers.DictField())

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
                if quantity <= 0:
                    raise serializers.ValidationError(f"Quantity must be positive for lot {lot_id}")

                if not CatalogItem.objects.filter(id=lot_id).exists():
                    raise serializers.ValidationError(f"Catalog item with id {lot_id} does not exist")

                validated_lots.append({
                    'id': lot_id,
                    'quantity': quantity
                })
            except (ValueError, TypeError):
                raise serializers.ValidationError(f"Invalid id or quantity format in lot: {lot}")

        return validated_lots

    @property
    def common_fields(self):
        return 'title', 'description', 'start_price', 'start_date', 'end_date', 'auction_type'

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
        lots_data = validated_data.pop('lots')
        common_data, specific_data = self._extract_data(validated_data)

        specific_auction = self.specific_model.objects.create(**specific_data)
        common_data['auction_type'] = ContentType.objects.get_for_model(self.specific_model)

        auction = Auction.objects.create(
            **common_data,
            owner=self.context['request'].user,
            object_id=specific_auction.id,
            specific_auction=specific_auction
        )

        auction_items = []
        for lot_data in lots_data:
            auction_items.append(AuctionItem(
                auction=auction,
                catalog_item_id=lot_data['id'],
                quantity=lot_data['quantity']
            ))

        AuctionItem.objects.bulk_create(auction_items)

        return auction

    @transaction.atomic
    def update(self, instance, validated_data):
        lots_data = validated_data.pop('lots', None)
        common_data, specific_data = self._extract_data(validated_data)

        new_auction_type = common_data['auction_type']
        old_auction_type = instance.auction_type.model

        if old_auction_type != new_auction_type:
            old_specific = instance.specific_auction
            new_specific = self.specific_model.objects.create(**specific_data)

            instance.auction_type = ContentType.objects.get_for_model(self.specific_model)
            instance.object_id = new_specific.id
            instance.specific_auction = new_specific

            old_specific.delete()
        else:
            for attr, value in specific_data.items():
                setattr(instance.specific_auction, attr, value)

        for attr, value in common_data.items():
            if attr != 'auction_type':
                setattr(instance, attr, value)

        instance.save()

        if lots_data is not None:
            instance.items.all().delete()
            auction_items = []
            for lot_data in lots_data:
                auction_items.append(AuctionItem(
                    auction=instance,
                    catalog_item_id=lot_data['id'],
                    quantity=lot_data['quantity']
                ))
            AuctionItem.objects.bulk_create(auction_items)

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
