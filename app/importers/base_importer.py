"""Base importer class with common import logic."""

from app.imports import create_import
from app.settings import get_setting
from app.utils.file_utils import check_duplicate


class BaseImporter:
    """Base class for all importers with common functionality."""

    def __init__(self, filepath):
        """Initialize importer with filepath.

        Args:
            filepath: Path to Excel file to import
        """
        self.filepath = filepath
        self.ticker_map = get_setting('ticker_map', {})
        self.errors = []
        self.rows_skipped = 0
        self.rows_imported = 0

    def check_duplicate(self):
        """Check if file has already been imported.

        Returns:
            Tuple of (is_duplicate, existing_import, file_hash)
        """
        return check_duplicate(self.filepath)

    def create_import_record(self, data_date, import_type, **kwargs):
        """Create an import audit record.

        Args:
            data_date: Date of the data (ISO string)
            import_type: Type of import (daily_portfolio, transactions, etc.)
            **kwargs: Additional fields (rows_imported, rows_skipped, etc.)

        Returns:
            Import record ID
        """
        import os
        from app.utils.file_utils import file_hash

        return create_import(
            filename=os.path.basename(self.filepath),
            filepath=self.filepath,
            file_hash=file_hash(self.filepath),
            data_date=data_date,
            import_type=import_type,
            rows_imported=kwargs.get('rows_imported', self.rows_imported),
            rows_skipped=kwargs.get('rows_skipped', self.rows_skipped),
            errors=kwargs.get('errors', self.errors),
            **{k: v for k, v in kwargs.items() if k not in ('rows_imported', 'rows_skipped', 'errors')}
        )

    def get_ticker_for_holding(self, tase_symbol, name_he):
        """Get ticker from ticker map.

        Args:
            tase_symbol: TASE symbol
            name_he: Hebrew name

        Returns:
            Ticker string or None
        """
        return self.ticker_map.get(tase_symbol) or self.ticker_map.get(name_he)
