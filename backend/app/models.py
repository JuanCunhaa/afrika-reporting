"""Contratos F00 ainda não migrados (métricas: F04/F05). Cadastro de clientes vive em orm.py/schemas.py (F01)."""
from pydantic import BaseModel


class MetricSnapshot(BaseModel):
    metric_id: str
    competence: str
    value: int | float | None = None
    source: str
    status: str
