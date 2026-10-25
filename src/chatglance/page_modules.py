"""The shared generated-page registry. Collectors live in refresh; renderers stay in their modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageModule:
    key: str
    name: str
    snapshot: str
    page_file: str


MODULES = {
    module.key: module for module in (
        PageModule("projects", "项目", "chatarch-projects.json", "projects-page.yml"),
        PageModule("servers", "服务器", "server-status.json", "server-page.yml"),
        PageModule("sites", "网站服务", "site-services.json", "site-services-page.yml"),
        PageModule("account-limits", "订阅详情", "account-limits.json", "account-limits-page.yml"),
    )
}


def render_page(key: str, data: dict, *, allow_controls: bool = True) -> dict:
    """Reuse each native Glance page renderer with an explicit control permission."""
    if key == "projects":
        from .projects import build_projects_page
        return build_projects_page(data, allow_controls=allow_controls)
    if key == "servers":
        from .servers import build_servers_page
        return build_servers_page(data, allow_controls=allow_controls)
    if key == "sites":
        from .sites import build_sites_page
        return build_sites_page(data)
    if key == "account-limits":
        from .account_limits import build_account_limits_page
        return build_account_limits_page(data, allow_controls=allow_controls)
    raise ValueError("unknown page module")
