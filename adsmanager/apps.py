from django.apps import AppConfig


class AdsmanagerConfig(AppConfig):
    """
    Django application configuration for the ads manager. This class is
    required so that Django can detect the app and apply any
    application-specific initialization. The name attribute must match
    the package name.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "adsmanager"
    verbose_name = "Gerenciador de Anúncios"