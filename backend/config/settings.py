"""
KampüsSes — Django ayarları.

Gizli bilgiler ve ortama özgü değerler koda yazılmaz, .env dosyasından okunur
(bkz. .env.example). Bu, Faz 1 analizindeki B4 bulgusunun düzeltmesidir.
"""
import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Yalnızca geliştirme ortamında: her başlatmada rastgele anahtar üretilir.
        SECRET_KEY = get_random_secret_key()
    else:
        raise RuntimeError("SECRET_KEY ortam değişkeni tanımlanmalı (DEBUG=False iken zorunlu).")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "accounts",
    "units",
    "reports",
    "interactions",
    "prioritization",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Veritabanı: DB_NAME tanımlıysa PostgreSQL, değilse SQLite kullanılır.
if os.getenv("DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

# Parolalar Django'nun PBKDF2 özetleme mekanizmasıyla saklanır.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    # Varsayılan: kimlik doğrulama zorunlu. Herkese açık uçlar bunu açıkça gevşetir.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 12,
}

# CORS yalnızca frontend adresine açıktır (NFR-03).
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")

# E-posta bildirimleri: geliştirmede konsola yazılır.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "kampusses@localhost")
# Gerçek gönderim için SMTP ayarları (FR-13). Şifre koda yazılmaz, yalnızca .env'den okunur (NFR-13).
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
# NFR-14: E-posta sunucusu yanıt vermezse istek en fazla bu kadar bekler; sonra yeniden deneme devreye girer.
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))

# İş kuralları
# Boş bırakılırsa her e-posta alan adı kabul edilir. Örn: "istun.edu.tr"
ALLOWED_EMAIL_DOMAINS = env_list("ALLOWED_EMAIL_DOMAINS", "")
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "pdf"]

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

JAZZMIN_SETTINGS = {
    "site_title": "KampüsSes Yönetim",
    "site_header": "KampüsSes",
    "site_brand": "KampüsSes",
    "welcome_sign": "KampüsSes yönetim paneline hoş geldiniz",
    "copyright": "KampüsSes",
}
