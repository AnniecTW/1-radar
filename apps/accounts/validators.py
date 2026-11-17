from datetime import date

from django.core.exceptions import ValidationError


def validate_graduation_year(year: int) -> None:
    current_year = date.today().year
    if not (current_year - 1 <= year <= current_year + 10):
        raise ValidationError('Enter a valid graduation year.')
