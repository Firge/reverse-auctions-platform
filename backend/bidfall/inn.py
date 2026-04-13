import re


INN_REGEX = re.compile(r"^(?:\d{10}|\d{12})$")


def normalize_inn(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\D", "", value.strip())


def _checksum(digits: str, coefficients: list[int]) -> int:
    total = sum(int(digit) * coefficient for digit, coefficient in zip(digits, coefficients))
    return total % 11 % 10


def is_valid_inn(inn: str) -> bool:
    if not INN_REGEX.fullmatch(inn):
        return False

    if len(inn) == 10:
        return _checksum(inn[:9], [2, 4, 10, 3, 5, 9, 4, 6, 8]) == int(inn[9])

    first = _checksum(inn[:10], [7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
    second = _checksum(inn[:11], [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
    return first == int(inn[10]) and second == int(inn[11])
