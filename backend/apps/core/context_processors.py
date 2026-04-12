from apps.core.branding import (
    build_page_title,
    get_seo_settings,
    get_system_favicon_url,
    get_system_logo_url,
    get_system_name,
)


def system_branding(request):
    system_name = get_system_name()
    seo = get_seo_settings()
    return {
        'system_name': system_name,
        'app_name': system_name,
        'system_title': build_page_title(),
        'system_logo_url': get_system_logo_url(),
        'system_favicon_url': get_system_favicon_url(),
        'seo': seo,
    }
