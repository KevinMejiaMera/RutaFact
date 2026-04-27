from django.conf import settings
from django.core.files.storage import default_storage
from django.templatetags.static import static


def get_setting_value(keys, default=''):
    if isinstance(keys, str):
        keys = [keys]

    try:
        from apps.settings.models import SystemSetting

        for key in keys:
            setting = SystemSetting.objects.filter(is_active=True, key=key).first()
            if setting and setting.value:
                value = setting.value.strip()
                if value:
                    return value
    except Exception:
        pass

    for key in keys:
        value = getattr(settings, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return default


def resolve_asset_url(value, fallback_static=None):
    if value:
        if value.startswith(('http://', 'https://', '/media/', '/static/')):
            return value
        try:
            return default_storage.url(value)
        except Exception:
            return value

    if fallback_static:
        return static(fallback_static)
    return ''


def get_system_name():
    """
    Nombre oficial del sistema para toda la aplicación.
    Prioridad:
    1. SystemSetting.SYSTEM_NAME
    2. otras claves equivalentes en SystemSetting
    3. settings cargados desde BD
    4. django.contrib.sites
    5. fallback
    """
    fallback_name = 'RutaFact'

    preferred_name = get_setting_value(['SYSTEM_NAME', 'SITE_NAME', 'APP_NAME', 'BRAND_NAME'])
    if preferred_name:
        return preferred_name

    try:
        from django.contrib.sites.models import Site

        current_site = Site.objects.get_current()
        if current_site and current_site.name and current_site.name != 'example.com':
            return current_site.name.strip()

    except Exception:
        pass

    return fallback_name


def build_page_title(page_title=None):
    system_name = get_system_name()
    if page_title:
        return f'{page_title} - {system_name}'
    return system_name


def get_system_logo_url():
    value = get_setting_value(['SYSTEM_LOGO', 'APP_LOGO', 'BRAND_LOGO'])
    return resolve_asset_url(value, 'img/logo.png')


def get_system_favicon_url():
    value = get_setting_value(['SYSTEM_FAVICON', 'APP_FAVICON', 'BRAND_FAVICON'])
    return resolve_asset_url(value, 'img/logo.png')



def get_seo_settings():
    system_name = get_system_name()
    meta_title = get_setting_value(['SEO_META_TITLE', 'META_TITLE'], system_name)
    meta_description = get_setting_value(
        ['SEO_META_DESCRIPTION', 'META_DESCRIPTION'],
        'Facturacion electronica moderna para Ecuador con integracion SRI, certificados digitales, API REST y automatizacion en tiempo real.'
    )
    meta_keywords = get_setting_value(
        ['SEO_META_KEYWORDS', 'META_KEYWORDS'],
        'facturacion electronica, SRI Ecuador, API REST, certificados digitales, comprobantes electronicos'
    )
    og_title = get_setting_value(['SEO_OG_TITLE', 'OG_TITLE'], meta_title)
    og_description = get_setting_value(['SEO_OG_DESCRIPTION', 'OG_DESCRIPTION'], meta_description)
    og_image = resolve_asset_url(
        get_setting_value(['SEO_OG_IMAGE', 'OG_IMAGE', 'SYSTEM_LOGO']),
        'images/favicon.png'
    )
    twitter_title = get_setting_value(['SEO_TWITTER_TITLE', 'TWITTER_TITLE'], og_title)
    twitter_description = get_setting_value(['SEO_TWITTER_DESCRIPTION', 'TWITTER_DESCRIPTION'], og_description)
    twitter_image = resolve_asset_url(
        get_setting_value(['SEO_TWITTER_IMAGE', 'TWITTER_IMAGE', 'SEO_OG_IMAGE', 'SYSTEM_LOGO']),
        'images/favicon.png'
    )
    robots = get_setting_value(['SEO_ROBOTS', 'META_ROBOTS'], 'index,follow')
    canonical_url = get_setting_value(['SEO_CANONICAL_URL', 'CANONICAL_URL'], '')
    custom_head = get_setting_value(['SEO_CUSTOM_HEAD', 'CUSTOM_HEAD'], '')

    return {
        'meta_title': meta_title,
        'meta_description': meta_description,
        'meta_keywords': meta_keywords,
        'og_title': og_title,
        'og_description': og_description,
        'og_image': og_image,
        'twitter_title': twitter_title,
        'twitter_description': twitter_description,
        'twitter_image': twitter_image,
        'robots': robots,
        'canonical_url': canonical_url,
        'custom_head': custom_head,
    }
