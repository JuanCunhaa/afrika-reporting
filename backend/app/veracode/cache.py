"""Cache TTL em memória (processo) para consultas de DESCOBERTA. Não substitui snapshots históricos (F05).

Chave = (tipo do escopo, id do escopo, id da conexão, região, credential_ref, impressão digital da credencial,
recurso, parâmetros). A impressão digital é um HMAC com sal aleatório do processo — nunca a credencial.
- Isolamento: escopos, conexões e credenciais diferentes nunca compartilham entrada.
- Só coletas COMPLETAS são armazenadas; incompletas são sempre refeitas.
- Invalidação manual por escopo (`invalidate_scope`) ou total (`clear`). Sem persistência em disco.
- Single-flight: pedidos simultâneos da mesma chave aguardam uma única coleta.
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

CacheKey = tuple


@dataclass
class _Entry:
    value: Any
    expires_at: float


class DiscoveryCache:
    def __init__(self, ttl: float, max_entries: int, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[CacheKey, _Entry] = OrderedDict()
        self._locks: dict[CacheKey, asyncio.Lock] = {}

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: CacheKey) -> tuple[Any, float] | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        remaining = entry.expires_at - self._clock()
        if remaining <= 0:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return entry.value, remaining

    def put(self, key: CacheKey, value: Any) -> None:
        if self.ttl <= 0:
            return
        self._data[key] = _Entry(value, self._clock() + self.ttl)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def invalidate_scope(self, scope_kind: str, scope_id: str) -> int:
        doomed = [k for k in self._data if k[0] == scope_kind and k[1] == scope_id]
        for k in doomed:
            del self._data[k]
        return len(doomed)

    def clear(self) -> int:
        n = len(self._data)
        self._data.clear()
        return n

    async def get_or_collect(self, key: CacheKey, collect: Callable[[], Awaitable[Any]],
                             is_complete: Callable[[Any], bool]) -> tuple[Any, bool, float | None]:
        """Devolve (valor, veio_do_cache, segundos_restantes)."""
        hit = self.get(key)
        if hit is not None:
            return hit[0], True, hit[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                hit = self.get(key)
                if hit is not None:
                    return hit[0], True, hit[1]
                value = await collect()
                if is_complete(value):
                    self.put(key, value)
                    return value, False, self.ttl if self.ttl > 0 else None
                return value, False, None
        finally:
            if not lock.locked() and self._locks.get(key) is lock:
                self._locks.pop(key, None)
