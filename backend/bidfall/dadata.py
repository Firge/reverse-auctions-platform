import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


class DadataError(Exception):
    pass


class DadataNotConfiguredError(DadataError):
    pass


class PartyNotFoundError(DadataError):
    pass


def find_party_by_inn(inn: str) -> dict:
    api_key = getattr(settings, "DADATA_API_KEY", "")
    if not api_key:
        raise DadataNotConfiguredError("Ключ DaData не настроен.")

    payload = json.dumps({"query": inn}).encode("utf-8")
    request = Request(
        getattr(settings, "DADATA_PARTY_URL", "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        message = f"DaData вернул ошибку HTTP {exc.code}."
        if details:
            message = f"{message} {details}".strip()
        raise DadataError(message) from exc
    except URLError as exc:
        raise DadataError("Сервис DaData сейчас недоступен.") from exc

    suggestions = data.get("suggestions") or []
    if not suggestions:
        raise PartyNotFoundError("ИНН не найден.")

    party = suggestions[0]
    party_data = party.get("data") or {}
    company_name = (
        party_data.get("name", {}).get("short_with_opf")
        or party.get("value")
        or party.get("unrestricted_value")
        or ""
    )
    if not company_name:
        raise PartyNotFoundError("ИНН не найден.")

    return {
        "inn": inn,
        "company_name": company_name,
        "full_name": party.get("unrestricted_value") or company_name,
        "ogrn": party_data.get("ogrn") or "",
        "kpp": party_data.get("kpp") or "",
    }
