"""Run the example receiver's tests without a Django project: `python runtests.py` (needs django)."""

import sys

import django
from django.conf import settings
from django.test.utils import get_runner

settings.configure(
    DEBUG=False,
    SECRET_KEY="example-only",
    ALLOWED_HOSTS=["testserver"],
    INSTALLED_APPS=["django.contrib.contenttypes", "detections"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    ROOT_URLCONF="detections.urls",
    MIDDLEWARE=["django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware"],
    USE_TZ=True,
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    CONDORIN_WEBHOOK_TOKEN="",  # real value comes from the environment / secret store
)
django.setup()
failures = get_runner(settings)().run_tests(["detections"])
sys.exit(bool(failures))
