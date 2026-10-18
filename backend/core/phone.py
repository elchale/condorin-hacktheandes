"""The one definition of a WhatsApp number: digits only, with the country code (10 to 15 digits)."""
import re

from django.core.validators import RegexValidator

PHONE_PATTERN = r'^\d{10,15}$'
PHONE_RE = re.compile(PHONE_PATTERN)
phone_validator = RegexValidator(PHONE_PATTERN, 'Solo dígitos con código de país, por ejemplo 51987654321.')
