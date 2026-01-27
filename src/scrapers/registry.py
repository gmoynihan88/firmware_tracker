import importlib
import pkgutil
from typing import Dict, Type, Optional, List

from src.scrapers.base import BaseScraper


class ScraperRegistry:
    """
    Registry for scraper plugins with auto-discovery.
    Scrapers are automatically discovered from the plugins package.
    """

    _scrapers: Dict[str, Type[BaseScraper]] = {}
    _initialized: bool = False

    @classmethod
    def _discover_plugins(cls):
        """Auto-discover scraper plugins from the plugins package."""
        if cls._initialized:
            return

        from src.scrapers import plugins

        for importer, modname, ispkg in pkgutil.iter_modules(plugins.__path__):
            try:
                module = importlib.import_module(f"src.scrapers.plugins.{modname}")
                # Look for classes that inherit from BaseScraper
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseScraper)
                        and attr is not BaseScraper
                        and attr.manufacturer_slug
                    ):
                        cls._scrapers[attr.manufacturer_slug] = attr
            except Exception as e:
                print(f"Error loading scraper plugin {modname}: {e}")

        cls._initialized = True

    @classmethod
    def register(cls, scraper_class: Type[BaseScraper]):
        """Manually register a scraper class."""
        if scraper_class.manufacturer_slug:
            cls._scrapers[scraper_class.manufacturer_slug] = scraper_class
        return scraper_class

    @classmethod
    def get(cls, scraper_type: str) -> Optional[Type[BaseScraper]]:
        """Get a scraper class by type identifier."""
        cls._discover_plugins()
        return cls._scrapers.get(scraper_type)

    @classmethod
    def create(cls, scraper_type: str) -> Optional[BaseScraper]:
        """Create an instance of a scraper by type."""
        scraper_class = cls.get(scraper_type)
        if scraper_class:
            return scraper_class()
        return None

    @classmethod
    def list_available(cls) -> List[str]:
        """List all available scraper types."""
        cls._discover_plugins()
        return list(cls._scrapers.keys())

    @classmethod
    def get_all_scrapers(cls) -> Dict[str, Type[BaseScraper]]:
        """Get all registered scrapers."""
        cls._discover_plugins()
        return cls._scrapers.copy()

    @classmethod
    def get_manufacturer_info(cls) -> List[dict]:
        """Get info about all registered manufacturers."""
        cls._discover_plugins()
        return [
            {
                "name": scraper.manufacturer_name,
                "slug": scraper.manufacturer_slug,
                "website": scraper.manufacturer_website,
            }
            for scraper in cls._scrapers.values()
        ]
