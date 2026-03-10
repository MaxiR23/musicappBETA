# test/services/conftest.py
import pytest

class MockQueryBuilder:
    """
    Simula el query builder fluent de Supabase.
    Cada método retorna self para soportar encadenamiento.
    execute() retorna un objeto con .data configurable.
    """

    def __init__(self, return_data: list | None = None):
        self._return_data = return_data if return_data is not None else []
        self.calls: list[dict] = []  # registro de llamadas para assertions

    # ── Configuración ────────────────────────────────────
    def set_return(self, data: list) -> "MockQueryBuilder":
        """Permite cambiar el return_data en medio de un test."""
        self._return_data = data
        return self

    # ── Query builder fluent ─────────────────────────────
    def select(self, columns: str = "*") -> "MockQueryBuilder":
        self.calls.append({"method": "select", "args": columns})
        return self

    def insert(self, data: dict | list) -> "MockQueryBuilder":
        self.calls.append({"method": "insert", "args": data})
        return self

    def upsert(self, data: dict | list, *, on_conflict: str = "") -> "MockQueryBuilder":
        self.calls.append({"method": "upsert", "args": data, "on_conflict": on_conflict})
        return self

    def update(self, data: dict) -> "MockQueryBuilder":
        self.calls.append({"method": "update", "args": data})
        return self

    def delete(self) -> "MockQueryBuilder":
        self.calls.append({"method": "delete"})
        return self

    def eq(self, column: str, value: object) -> "MockQueryBuilder":
        self.calls.append({"method": "eq", "column": column, "value": value})
        return self

    def neq(self, column: str, value: object) -> "MockQueryBuilder":
        self.calls.append({"method": "neq", "column": column, "value": value})
        return self

    def in_(self, column: str, values: list) -> "MockQueryBuilder":
        self.calls.append({"method": "in_", "column": column, "values": values})
        return self

    def order(self, column: str, *, desc: bool = False) -> "MockQueryBuilder":
        self.calls.append({"method": "order", "column": column, "desc": desc})
        return self

    def limit(self, count: int) -> "MockQueryBuilder":
        self.calls.append({"method": "limit", "count": count})
        return self

    def single(self) -> "MockQueryBuilder":
        self.calls.append({"method": "single"})
        return self

    def execute(self) -> "MockResult":
        return MockResult(self._return_data)

class MockResult:
    """Simula el resultado de .execute() de Supabase."""

    def __init__(self, data: list | None = None):
        self.data = data if data is not None else []

class MockDB:
    """
    Implementa DBClient protocol para tests.

    Uso básico:
        db = MockDB()
        db.set_table_data("play_events", [{"id": "abc"}])
        result = log_play(db, user_id="u1", track_id="t1")

    Inspeccionar llamadas:
        builder = db.get_builder("play_events")
        assert builder.calls[0]["method"] == "insert"
    """

    def __init__(self):
        self._tables: dict[str, MockQueryBuilder] = {}

    def set_table_data(self, table_name: str, data: list) -> None:
        """Configura qué datos retorna execute() para una tabla."""
        self._get_or_create(table_name).set_return(data)

    def get_builder(self, table_name: str) -> MockQueryBuilder:
        """Accede al builder de una tabla para assertions."""
        return self._get_or_create(table_name)

    def reset(self) -> None:
        """Limpia todos los builders entre tests."""
        self._tables.clear()

    def _get_or_create(self, table_name: str) -> MockQueryBuilder:
        if table_name not in self._tables:
            self._tables[table_name] = MockQueryBuilder()
        return self._tables[table_name]

    # ── DBClient protocol ────────────────────────────────
    def table(self, table_name: str) -> MockQueryBuilder:
        return self._get_or_create(table_name)

# ── Fixtures ─────────────────────────────────────────────
@pytest.fixture
def mock_db() -> MockDB:
    """DB limpia por cada test."""
    return MockDB()